from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import BacktestConfig
from .database import get_store
from .market_calendar import now_new_york


class DataHealthChecker:
    """?????????????????????????"""

    def __init__(self, config: BacktestConfig | None = None, output_dir: Path = Path("outputs")) -> None:
        self.config = config or BacktestConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        rows = [self._check_symbol(symbol) for symbol in self.config.symbols]
        frame = pd.DataFrame(rows)
        summary = self._summary(frame)
        frame.to_csv(self.output_dir / "data_health.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "data_health_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame, summary)
        get_store().append_generic_frame("data_health", "data_health.csv", frame)
        get_store().append_generic_frame("data_health_summary", "data_health_summary.csv", summary)
        return summary

    def _check_symbol(self, symbol: str) -> dict[str, object]:
        path = self.config.cache_dir / f"{symbol}.csv"
        now = pd.Timestamp.now()
        is_watch_only = symbol in set(getattr(self.config, "watch_only_symbols", []))
        if not path.exists() or path.stat().st_size == 0:
            return {
                "time": now,
                "symbol": symbol,
                "is_watch_only": is_watch_only,
                "status": "MISSING",
                "rows": 0,
                "latest_date": "",
                "cache_age_hours": 0.0,
                "lag_calendar_days": 999,
                "reason": "cache file missing",
            }
        try:
            frame = pd.read_csv(path, parse_dates=["date"])
            latest_date = pd.Timestamp(frame["date"].max()).date()
            rows = len(frame)
        except Exception as exc:
            return {
                "time": now,
                "symbol": symbol,
                "is_watch_only": is_watch_only,
                "status": "ERROR",
                "rows": 0,
                "latest_date": "",
                "cache_age_hours": round((path.stat().st_mtime_ns / 1e9), 2),
                "lag_calendar_days": 999,
                "reason": f"{type(exc).__name__}: {exc}",
            }

        cache_age_hours = (pd.Timestamp.now().timestamp() - path.stat().st_mtime) / 3600
        lag_calendar_days = (now_new_york().date() - latest_date).days
        status = "OK"
        reasons = []
        if rows < 120:
            status = "WARN"
            reasons.append("short history")
        if lag_calendar_days > 5:
            status = "STALE"
            reasons.append("latest date too old")
        elif lag_calendar_days > 2:
            status = "WARN"
            reasons.append("latest date lagging")
        if cache_age_hours > self.config.cache_max_age_hours * 2:
            status = "WARN" if status == "OK" else status
            reasons.append("cache file is old")
        return {
            "time": now,
            "symbol": symbol,
            "is_watch_only": is_watch_only,
            "status": status,
            "rows": rows,
            "latest_date": latest_date.isoformat(),
            "cache_age_hours": round(cache_age_hours, 2),
            "lag_calendar_days": lag_calendar_days,
            "reason": "; ".join(reasons) if reasons else "fresh enough",
        }

    @staticmethod
    def _summary(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame([{"time": pd.Timestamp.now(), "status": "NO_DATA", "ok_count": 0, "warn_count": 0, "stale_count": 0}])
        core = frame
        if "is_watch_only" in frame.columns:
            core = frame[~frame["is_watch_only"].astype(bool)]
        if core.empty:
            core = frame
        status_counts = core["status"].value_counts().to_dict()
        all_status_counts = frame["status"].value_counts().to_dict()
        worst = "OK"
        if status_counts.get("ERROR", 0) or status_counts.get("MISSING", 0):
            worst = "ERROR"
        elif status_counts.get("STALE", 0):
            worst = "STALE"
        elif status_counts.get("WARN", 0):
            worst = "WARN"
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "status": worst,
                    "ok_count": int(status_counts.get("OK", 0)),
                    "warn_count": int(status_counts.get("WARN", 0)),
                    "stale_count": int(status_counts.get("STALE", 0)),
                    "missing_count": int(status_counts.get("MISSING", 0)),
                    "error_count": int(status_counts.get("ERROR", 0)),
                    "watch_only_warn_count": int(all_status_counts.get("WARN", 0) - status_counts.get("WARN", 0)),
                    "max_lag_calendar_days": int(frame["lag_calendar_days"].max()),
                    "oldest_cache_age_hours": float(frame["cache_age_hours"].max()),
                }
            ]
        )

    def _write_report(self, frame: pd.DataFrame, summary: pd.DataFrame) -> None:
        row = summary.iloc[0] if not summary.empty else {}
        lines = [
            "# Data Health Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            f"- Status: {row.get('status', 'NO_DATA')}",
            f"- Max lag days: {row.get('max_lag_calendar_days', '')}",
            f"- Oldest cache age hours: {row.get('oldest_cache_age_hours', '')}",
            "",
            "| symbol | watch_only | status | latest_date | rows | lag_calendar_days | reason |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in frame.to_dict(orient="records"):
            lines.append(
                f"| {item['symbol']} | {item.get('is_watch_only', False)} | {item['status']} | {item['latest_date']} | "
                f"{item['rows']} | {item['lag_calendar_days']} | {item['reason']} |"
            )
        (self.output_dir / "data_health_report.md").write_text("\n".join(lines), encoding="utf-8")
