from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from .config import FundamentalDataConfig
from .database import get_store


METRIC_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "net_income": ["NetIncomeLoss"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "stockholders_equity": ["StockholdersEquity"],
    "diluted_eps": ["EarningsPerShareDiluted"],
}


class FundamentalDataAnalyzer:
    """读取 SEC EDGAR Companyfacts 公开基本面数据。"""

    def __init__(self, config: FundamentalDataConfig | None = None, output_dir: Path | None = None) -> None:
        self.config = config or FundamentalDataConfig()
        self.output_dir = output_dir or self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        rows = []
        for symbol, cik in self.config.cik_by_symbol.items():
            payload, error = self._download_companyfacts(cik)
            if error:
                rows.append(self._error_row(symbol, cik, error))
                continue
            rows.extend(self._extract_metrics(symbol, cik, payload))

        detail = pd.DataFrame(rows)
        summary = self._summary(detail)
        detail.to_csv(self.output_dir / "fundamental_snapshot.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "fundamental_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(detail, summary)
        get_store().append_generic_frame("fundamental_snapshot", "fundamental_snapshot.csv", detail)
        get_store().append_generic_frame("fundamental_summary", "fundamental_summary.csv", summary)
        return summary

    def _download_companyfacts(self, cik: str) -> tuple[dict[str, object], str]:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        headers = {
            "User-Agent": self.config.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_count + 1):
            try:
                response = requests.get(url, headers=headers, timeout=self.config.timeout_seconds)
                response.raise_for_status()
                return response.json(), ""
            except Exception as exc:
                last_error = exc
                print(f"SEC CIK{cik} 下载失败，第 {attempt} 次: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(self.config.retry_wait_seconds)
        return {}, f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error"

    def _extract_metrics(self, symbol: str, cik: str, payload: dict[str, object]) -> list[dict[str, object]]:
        facts = payload.get("facts", {}) if isinstance(payload, dict) else {}
        us_gaap = facts.get("us-gaap", {}) if isinstance(facts, dict) else {}
        rows = []
        for metric, tags in METRIC_TAGS.items():
            row = self._extract_metric(symbol, cik, metric, tags, us_gaap)
            rows.append(row)
        return rows

    def _extract_metric(self, symbol: str, cik: str, metric: str, tags: list[str], us_gaap: dict[str, object]) -> dict[str, object]:
        candidates: list[tuple[str, str, dict[str, object]]] = []
        for tag in tags:
            concept = us_gaap.get(tag)
            if not isinstance(concept, dict):
                continue
            units = concept.get("units", {})
            if not isinstance(units, dict):
                continue
            for unit_name in _preferred_units(metric):
                facts = units.get(unit_name)
                if not facts:
                    continue
                fact = _latest_fact(facts)
                if fact:
                    candidates.append((tag, unit_name, fact))
        if candidates:
            tag, unit_name, fact = sorted(candidates, key=lambda item: (str(item[2].get("filed", "")), str(item[2].get("end", ""))))[-1]
            return {
                "time": pd.Timestamp.now(),
                "symbol": symbol,
                "cik": cik,
                "metric": metric,
                "status": "OK",
                "tag": tag,
                "unit": unit_name,
                "value": fact.get("val", 0.0),
                "period_end": fact.get("end", ""),
                "filed": fact.get("filed", ""),
                "form": fact.get("form", ""),
                "fiscal_year": fact.get("fy", ""),
                "fiscal_period": fact.get("fp", ""),
                "reason": "latest SEC companyfacts observation",
            }
        return self._metric_missing_row(symbol, cik, metric)

    @staticmethod
    def _summary(detail: pd.DataFrame) -> pd.DataFrame:
        if detail.empty:
            return pd.DataFrame(
                [
                    {
                        "time": pd.Timestamp.now(),
                        "status": "NO_DATA",
                        "symbols": 0,
                        "metrics_ok": 0,
                        "metrics_missing": 0,
                        "reason": "no SEC data",
                    }
                ]
            )
        ok_count = int((detail["status"].astype(str) == "OK").sum())
        missing_count = int((detail["status"].astype(str) != "OK").sum())
        status = "OK" if missing_count == 0 else "WARN" if ok_count else "ERROR"
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "status": status,
                    "symbols": int(detail["symbol"].nunique()),
                    "metrics_ok": ok_count,
                    "metrics_missing": missing_count,
                    "reason": "SEC companyfacts loaded" if ok_count else "SEC companyfacts unavailable",
                }
            ]
        )

    @staticmethod
    def _error_row(symbol: str, cik: str, error: str) -> dict[str, object]:
        return {
            "time": pd.Timestamp.now(),
            "symbol": symbol,
            "cik": cik,
            "metric": "companyfacts",
            "status": "ERROR",
            "tag": "",
            "unit": "",
            "value": 0.0,
            "period_end": "",
            "filed": "",
            "form": "",
            "fiscal_year": "",
            "fiscal_period": "",
            "reason": error,
        }

    @staticmethod
    def _metric_missing_row(symbol: str, cik: str, metric: str) -> dict[str, object]:
        return {
            "time": pd.Timestamp.now(),
            "symbol": symbol,
            "cik": cik,
            "metric": metric,
            "status": "MISSING",
            "tag": "",
            "unit": "",
            "value": 0.0,
            "period_end": "",
            "filed": "",
            "form": "",
            "fiscal_year": "",
            "fiscal_period": "",
            "reason": "metric tag not found",
        }

    def _write_report(self, detail: pd.DataFrame, summary: pd.DataFrame) -> None:
        row = summary.iloc[0] if not summary.empty else {}
        lines = [
            "# Fundamental Data Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            f"- Status: {row.get('status', 'NO_DATA')}",
            f"- Symbols: {row.get('symbols', 0)}",
            f"- Metrics OK: {row.get('metrics_ok', 0)}",
            f"- Missing/Error metrics: {row.get('metrics_missing', 0)}",
            "",
            "| symbol | metric | value | unit | period_end | filed | form | status |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in detail.to_dict(orient="records"):
            lines.append(
                f"| {item.get('symbol', '')} | {item.get('metric', '')} | {item.get('value', '')} | "
                f"{item.get('unit', '')} | {item.get('period_end', '')} | {item.get('filed', '')} | "
                f"{item.get('form', '')} | {item.get('status', '')} |"
            )
        (self.output_dir / "fundamental_report.md").write_text("\n".join(lines), encoding="utf-8")


def _preferred_units(metric: str) -> list[str]:
    if metric == "diluted_eps":
        return ["USD/shares", "USD/shares"]
    return ["USD", "shares"]


def _latest_fact(facts: list[dict[str, object]]) -> dict[str, object]:
    valid = [
        fact
        for fact in facts
        if isinstance(fact, dict)
        and fact.get("val") is not None
        and str(fact.get("form", "")) in {"10-K", "10-Q", "20-F", "40-F"}
        and fact.get("end")
        and fact.get("filed")
    ]
    if not valid:
        return {}
    valid.sort(key=lambda item: (str(item.get("filed", "")), str(item.get("end", ""))))
    return valid[-1]
