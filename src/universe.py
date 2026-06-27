from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .config import LocalPaperConfig
from .database import get_store


class UniverseFilter:
    """股票池过滤器：扩大研究范围，但只允许高质量候选进入买入名单。"""

    def __init__(self, config: LocalPaperConfig | None = None, output_dir: Path | None = None) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir or self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.metadata = self._load_metadata()

    def run(self, market_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        rows = [self._row(symbol, frame) for symbol, frame in market_data.items()]
        frame = pd.DataFrame(rows)
        if frame.empty:
            frame = self._empty_frame()
        else:
            frame = frame.sort_values(["tradable_passed", "symbol"], ascending=[False, True]).reset_index(drop=True)
        summary = self._summary(frame)
        frame.to_csv(self.output_dir / "universe_filter.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "universe_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame, summary)
        get_store().append_generic_frame("universe_filter", "universe_filter.csv", frame)
        get_store().append_generic_frame("universe_summary", "universe_summary.csv", summary)
        return frame

    def tradable_symbols(self, market_data: dict[str, pd.DataFrame]) -> list[str]:
        frame = self.run(market_data)
        if frame.empty or "tradable_passed" not in frame.columns:
            return []
        return frame[_bool_series(frame["tradable_passed"])]["symbol"].astype(str).tolist()

    def _row(self, symbol: str, frame: pd.DataFrame) -> dict[str, object]:
        meta = self.metadata.get(symbol, {})
        watch_only = _bool(meta.get("watch_only")) or symbol in set(getattr(self.config, "watch_only_symbols", []))
        configured_tradable = _bool(meta.get("tradable"), default=True)
        clean = frame.dropna(subset=["close"]).sort_index() if frame is not None and not frame.empty else pd.DataFrame()
        rows = int(len(clean))
        latest_date = ""
        latest_price = 0.0
        avg_dollar_volume_20d = 0.0
        reasons = []

        if clean.empty:
            reasons.append("no price data")
        else:
            close = clean["close"].astype(float)
            volume = clean.get("volume", pd.Series(0.0, index=clean.index)).astype(float)
            latest_date = pd.Timestamp(clean.index[-1]).date().isoformat()
            latest_price = float(close.iloc[-1])
            avg_dollar_volume_20d = float((close * volume).tail(20).mean())

        history_ok = rows >= int(getattr(self.config, "universe_min_history_rows", 500))
        volume_ok = avg_dollar_volume_20d >= float(getattr(self.config, "universe_min_avg_dollar_volume", 50_000_000.0))
        min_price = float(getattr(self.config, "universe_min_price", 5.0))
        max_price = float(getattr(self.config, "universe_max_price", 2_000.0))
        price_ok = min_price <= latest_price <= max_price

        if not configured_tradable:
            reasons.append("configured non-tradable")
        if watch_only:
            reasons.append("watch-only")
        if not history_ok:
            reasons.append(f"history rows {rows} < {int(getattr(self.config, 'universe_min_history_rows', 500))}")
        if not volume_ok:
            reasons.append(
                "avg dollar volume "
                f"{avg_dollar_volume_20d:.0f} < {float(getattr(self.config, 'universe_min_avg_dollar_volume', 50_000_000.0)):.0f}"
            )
        if not price_ok:
            reasons.append(f"price {latest_price:.2f} outside [{min_price:.2f}, {max_price:.2f}]")

        data_passed = bool(clean is not None and not clean.empty and history_ok and volume_ok and price_ok)
        tradable_passed = bool(data_passed and configured_tradable and not watch_only)
        return {
            "time": pd.Timestamp.now(),
            "symbol": symbol,
            "name": meta.get("name", ""),
            "sector": meta.get("sector", ""),
            "asset_type": meta.get("asset_type", ""),
            "source": meta.get("source", ""),
            "configured_tradable": configured_tradable,
            "watch_only": watch_only,
            "data_passed": data_passed,
            "tradable_passed": tradable_passed,
            "rows": rows,
            "latest_date": latest_date,
            "latest_price": round(latest_price, 4),
            "avg_dollar_volume_20d": round(avg_dollar_volume_20d, 2),
            "history_ok": history_ok,
            "volume_ok": volume_ok,
            "price_ok": price_ok,
            "reject_reason": "; ".join(reasons) if reasons else "passed",
        }

    def _load_metadata(self) -> dict[str, dict[str, object]]:
        path = Path(getattr(self.config, "universe_file", ""))
        if not path.exists():
            return {}
        metadata: dict[str, dict[str, object]] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol", "")).strip().upper()
                if symbol:
                    metadata[symbol] = row
        return metadata

    @staticmethod
    def _empty_frame() -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "time",
                "symbol",
                "name",
                "sector",
                "asset_type",
                "source",
                "configured_tradable",
                "watch_only",
                "data_passed",
                "tradable_passed",
                "rows",
                "latest_date",
                "latest_price",
                "avg_dollar_volume_20d",
                "history_ok",
                "volume_ok",
                "price_ok",
                "reject_reason",
            ]
        )

    def _summary(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(
                [
                    {
                        "time": pd.Timestamp.now(),
                        "total_symbols": 0,
                        "tradable_passed": 0,
                        "watch_only": 0,
                        "rejected": 0,
                        "status": "NO_DATA",
                    }
                ]
            )
        total = len(frame)
        passed = int(_bool_series(frame["tradable_passed"]).sum())
        watch_only = int(_bool_series(frame["watch_only"]).sum())
        rejected = total - passed
        status = "OK" if passed >= 20 else "WARN" if passed >= 5 else "ERROR"
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "total_symbols": total,
                    "tradable_passed": passed,
                    "watch_only": watch_only,
                    "rejected": rejected,
                    "status": status,
                    "min_history_rows": int(getattr(self.config, "universe_min_history_rows", 500)),
                    "min_avg_dollar_volume": float(getattr(self.config, "universe_min_avg_dollar_volume", 50_000_000.0)),
                }
            ]
        )

    def _write_report(self, frame: pd.DataFrame, summary: pd.DataFrame) -> None:
        row = summary.iloc[0] if not summary.empty else {}
        lines = [
            "# Universe Filter Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            f"- Status: {row.get('status', 'NO_DATA')}",
            f"- Total symbols: {row.get('total_symbols', 0)}",
            f"- Tradable passed: {row.get('tradable_passed', 0)}",
            f"- Rejected: {row.get('rejected', 0)}",
            "",
            "| symbol | passed | watch_only | rows | latest_date | latest_price | avg_dollar_volume_20d | reason |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in frame.to_dict(orient="records"):
            lines.append(
                f"| {item.get('symbol', '')} | {item.get('tradable_passed', False)} | "
                f"{item.get('watch_only', False)} | {item.get('rows', 0)} | "
                f"{item.get('latest_date', '')} | {float(item.get('latest_price', 0.0)):.2f} | "
                f"{float(item.get('avg_dollar_volume_20d', 0.0)):.0f} | {item.get('reject_reason', '')} |"
            )
        (self.output_dir / "universe_report.md").write_text("\n".join(lines), encoding="utf-8")


def load_tradable_universe(output_dir: Path = Path("outputs")) -> set[str]:
    """从最近一次过滤结果读取可交易股票；没有结果时返回空集合。"""
    path = output_dir / "universe_filter.csv"
    if not path.exists() or path.stat().st_size == 0:
        return set()
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return set()
    if frame.empty or "tradable_passed" not in frame.columns:
        return set()
    passed = frame[_bool_series(frame["tradable_passed"])]
    return set(passed["symbol"].astype(str))


def filter_market_data_for_tradable(market_data: dict[str, pd.DataFrame], output_dir: Path = Path("outputs")) -> dict[str, pd.DataFrame]:
    """只保留最近一次股票池过滤通过的标的；没有过滤结果时保留原始数据。"""
    allowed = load_tradable_universe(output_dir)
    if not allowed:
        return market_data
    return {symbol: frame for symbol, frame in market_data.items() if symbol in allowed}


def _bool(value: object, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _bool_series(series: pd.Series) -> pd.Series:
    return series.map(lambda value: _bool(value))
