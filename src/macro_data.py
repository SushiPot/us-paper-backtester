from __future__ import annotations

import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from .config import MacroDataConfig
from .database import get_store


class MacroDataAnalyzer:
    """?? FRED ????????????????????"""

    def __init__(self, config: MacroDataConfig | None = None, output_dir: Path | None = None) -> None:
        self.config = config or MacroDataConfig()
        self.output_dir = output_dir or self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        rows = []
        series_frames: dict[str, pd.DataFrame] = {}
        for series_id, label in self.config.series.items():
            frame = self._download_series(series_id)
            series_frames[series_id] = frame
            rows.append(self._series_row(series_id, label, frame))

        detail = pd.DataFrame(rows)
        summary = self._summary(detail)
        detail.to_csv(self.output_dir / "macro_indicators.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "macro_environment_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(detail, summary)
        get_store().append_generic_frame("macro_indicators", "macro_indicators.csv", detail)
        get_store().append_generic_frame("macro_environment_summary", "macro_environment_summary.csv", summary)
        return summary

    def _download_series(self, series_id: str) -> pd.DataFrame:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_count + 1):
            try:
                response = requests.get(url, timeout=self.config.timeout_seconds)
                response.raise_for_status()
                frame = pd.read_csv(StringIO(response.text))
                if frame.empty or series_id not in frame.columns:
                    raise ValueError(f"{series_id} returned no usable CSV data")
                frame = frame.rename(columns={"observation_date": "date", series_id: "value"})
                frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
                frame["value"] = pd.to_numeric(frame["value"].replace(".", pd.NA), errors="coerce")
                frame = frame.dropna(subset=["date", "value"]).sort_values("date")
                if frame.empty:
                    raise ValueError(f"{series_id} has no numeric observations")
                return frame
            except Exception as exc:
                last_error = exc
                print(f"{series_id} FRED ?????? {attempt} ?: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(self.config.retry_wait_seconds)

        return pd.DataFrame(
            [
                {
                    "date": pd.NaT,
                    "value": pd.NA,
                    "error": f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error",
                }
            ]
        )

    def _series_row(self, series_id: str, label: str, frame: pd.DataFrame) -> dict[str, object]:
        now = pd.Timestamp.now()
        if frame.empty or frame["value"].dropna().empty:
            return {
                "time": now,
                "series_id": series_id,
                "label": label,
                "status": "ERROR",
                "latest_date": "",
                "latest_value": 0.0,
                "change_20_obs": 0.0,
                "change_60_obs": 0.0,
                "yoy_pct": 0.0,
                "reason": "no usable data",
            }

        clean = frame.dropna(subset=["value"]).copy()
        latest = clean.iloc[-1]
        latest_value = float(latest["value"])
        change_20 = _period_change(clean["value"], 20)
        change_60 = _period_change(clean["value"], 60)
        yoy = _period_pct_change(clean["value"], 12) if series_id in {"CPIAUCSL", "UNRATE", "FEDFUNDS"} else 0.0
        return {
            "time": now,
            "series_id": series_id,
            "label": label,
            "status": "OK",
            "latest_date": pd.Timestamp(latest["date"]).date().isoformat(),
            "latest_value": latest_value,
            "change_20_obs": change_20,
            "change_60_obs": change_60,
            "yoy_pct": yoy,
            "reason": "fresh enough",
        }

    @staticmethod
    def _summary(detail: pd.DataFrame) -> pd.DataFrame:
        if detail.empty or "series_id" not in detail.columns:
            return pd.DataFrame(
                [
                    {
                        "time": pd.Timestamp.now(),
                        "macro_status": "NO_DATA",
                        "recommended_action": "OBSERVE_ONLY",
                        "risk_score": 0,
                        "reason": "no macro data",
                    }
                ]
            )

        values = {str(row["series_id"]): row for _, row in detail.iterrows()}
        risk_score = 0
        reasons: list[str] = []

        vix = _row_value(values, "VIXCLS")
        if vix >= 30:
            risk_score += 3
            reasons.append("VIX above 30")
        elif vix >= 22:
            risk_score += 1
            reasons.append("VIX above 22")

        curve = _row_value(values, "T10Y2Y")
        if curve < -0.50:
            risk_score += 2
            reasons.append("yield curve deeply inverted")
        elif curve < 0:
            risk_score += 1
            reasons.append("yield curve inverted")

        dgs10_change = _row_change_60(values, "DGS10")
        if dgs10_change >= 0.75:
            risk_score += 1
            reasons.append("10Y yield rose more than 75bp over 60 observations")

        unrate_change = _row_change_20(values, "UNRATE")
        if unrate_change >= 0.30:
            risk_score += 2
            reasons.append("unemployment rate rising")

        missing_count = int((detail["status"].astype(str) != "OK").sum())
        if missing_count:
            risk_score += 1
            reasons.append(f"macro series errors={missing_count}")

        if risk_score >= 4:
            macro_status = "RISK_OFF"
            action = "PAUSE_NEW_BUYS"
        elif risk_score >= 2:
            macro_status = "NEUTRAL"
            action = "REDUCE_NEW_BUY_SIZE"
        else:
            macro_status = "RISK_ON"
            action = "ALLOW_NORMAL_SIMULATION"

        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "macro_status": macro_status,
                    "recommended_action": action,
                    "risk_score": risk_score,
                    "vix": vix,
                    "ten_year_yield": _row_value(values, "DGS10"),
                    "yield_curve_10y2y": curve,
                    "fed_funds": _row_value(values, "FEDFUNDS"),
                    "unemployment_rate": _row_value(values, "UNRATE"),
                    "cpi_yoy_pct": _row_yoy(values, "CPIAUCSL"),
                    "reason": "; ".join(reasons) if reasons else "macro backdrop acceptable",
                }
            ]
        )

    def _write_report(self, detail: pd.DataFrame, summary: pd.DataFrame) -> None:
        row = summary.iloc[0] if not summary.empty else {}
        lines = [
            "# Macro Environment Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            f"- Macro status: {row.get('macro_status', 'NO_DATA')}",
            f"- Recommended action: {row.get('recommended_action', 'OBSERVE_ONLY')}",
            f"- Risk score: {row.get('risk_score', 0)}",
            f"- Reason: {row.get('reason', '')}",
            "",
            "| series | latest_date | latest_value | change_20_obs | change_60_obs | reason |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in detail.to_dict(orient="records"):
            lines.append(
                f"| {item.get('series_id', '')} | {item.get('latest_date', '')} | "
                f"{item.get('latest_value', '')} | {item.get('change_20_obs', '')} | "
                f"{item.get('change_60_obs', '')} | {item.get('reason', '')} |"
            )
        (self.output_dir / "macro_environment_report.md").write_text("\n".join(lines), encoding="utf-8")


def _period_change(values: pd.Series, periods: int) -> float:
    if len(values) <= periods:
        return 0.0
    return float(values.iloc[-1] - values.iloc[-periods - 1])


def _period_pct_change(values: pd.Series, periods: int) -> float:
    if len(values) <= periods:
        return 0.0
    base = float(values.iloc[-periods - 1])
    if base == 0:
        return 0.0
    return float(values.iloc[-1] / base - 1.0)


def _row_value(values: dict[str, pd.Series], series_id: str) -> float:
    row = values.get(series_id)
    if row is None:
        return 0.0
    return float(row.get("latest_value", 0.0) or 0.0)


def _row_change_20(values: dict[str, pd.Series], series_id: str) -> float:
    row = values.get(series_id)
    if row is None:
        return 0.0
    return float(row.get("change_20_obs", 0.0) or 0.0)


def _row_change_60(values: dict[str, pd.Series], series_id: str) -> float:
    row = values.get(series_id)
    if row is None:
        return 0.0
    return float(row.get("change_60_obs", 0.0) or 0.0)


def _row_yoy(values: dict[str, pd.Series], series_id: str) -> float:
    row = values.get(series_id)
    if row is None:
        return 0.0
    return float(row.get("yoy_pct", 0.0) or 0.0)
