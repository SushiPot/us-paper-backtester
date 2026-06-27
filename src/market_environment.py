from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import BacktestConfig
from .database import get_store


class MarketEnvironmentAnalyzer:
    """? SPY/QQQ ??????????????????????"""

    def __init__(self, config: BacktestConfig | None = None, output_dir: Path = Path("outputs")) -> None:
        self.config = config or BacktestConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        rows = []
        for symbol in ["SPY", "QQQ"]:
            rows.append(self._analyze_symbol(symbol))
        detail = pd.DataFrame(rows)
        summary = self._summary(detail)
        detail.to_csv(self.output_dir / "market_environment.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "market_environment_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(detail, summary)
        get_store().append_generic_frame("market_environment", "market_environment.csv", detail)
        get_store().append_generic_frame("market_environment_summary", "market_environment_summary.csv", summary)
        return summary

    def _analyze_symbol(self, symbol: str) -> dict[str, object]:
        path = self.config.cache_dir / f"{symbol}.csv"
        if not path.exists() or path.stat().st_size == 0:
            return {"symbol": symbol, "status": "NO_DATA", "reason": "missing cache"}
        frame = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
        if len(frame) < 220:
            return {"symbol": symbol, "status": "NO_DATA", "reason": "insufficient history"}
        close = frame["close"].astype(float)
        latest_close = float(close.iloc[-1])
        ma50 = float(close.rolling(50).mean().iloc[-1])
        ma200 = float(close.rolling(200).mean().iloc[-1])
        return_5d = float(close.pct_change(5).iloc[-1])
        return_20d = float(close.pct_change(20).iloc[-1])
        realized_vol_20d = float(close.pct_change().rolling(20).std().iloc[-1] * (252**0.5))
        above_ma200 = latest_close > ma200
        above_ma50 = latest_close > ma50
        status = "RISK_ON"
        reasons = []
        if not above_ma200:
            status = "RISK_OFF"
            reasons.append("below MA200")
        elif not above_ma50:
            status = "NEUTRAL"
            reasons.append("below MA50")
        if return_5d <= -0.05:
            status = "RISK_OFF"
            reasons.append("5d drawdown worse than -5%")
        elif return_5d <= -0.03 and status == "RISK_ON":
            status = "NEUTRAL"
            reasons.append("5d drawdown worse than -3%")
        if realized_vol_20d >= 0.35:
            status = "RISK_OFF"
            reasons.append("20d annualized vol above 35%")
        elif realized_vol_20d >= 0.25 and status == "RISK_ON":
            status = "NEUTRAL"
            reasons.append("20d annualized vol above 25%")
        return {
            "time": pd.Timestamp.now(),
            "symbol": symbol,
            "status": status,
            "latest_date": pd.Timestamp(frame["date"].iloc[-1]).date().isoformat(),
            "close": latest_close,
            "ma50": ma50,
            "ma200": ma200,
            "above_ma50": above_ma50,
            "above_ma200": above_ma200,
            "return_5d": return_5d,
            "return_20d": return_20d,
            "realized_vol_20d": realized_vol_20d,
            "reason": "; ".join(reasons) if reasons else "trend and volatility acceptable",
        }

    @staticmethod
    def _summary(detail: pd.DataFrame) -> pd.DataFrame:
        if detail.empty:
            return pd.DataFrame([{"time": pd.Timestamp.now(), "market_status": "NO_DATA", "recommended_action": "OBSERVE_ONLY"}])
        statuses = detail["status"].astype(str).tolist()
        if "RISK_OFF" in statuses:
            market_status = "RISK_OFF"
            action = "PAUSE_NEW_BUYS"
        elif "NEUTRAL" in statuses:
            market_status = "NEUTRAL"
            action = "REDUCE_NEW_BUY_SIZE"
        elif all(status == "RISK_ON" for status in statuses):
            market_status = "RISK_ON"
            action = "ALLOW_NORMAL_SIMULATION"
        else:
            market_status = "NO_DATA"
            action = "OBSERVE_ONLY"
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "market_status": market_status,
                    "recommended_action": action,
                    "risk_off_count": statuses.count("RISK_OFF"),
                    "neutral_count": statuses.count("NEUTRAL"),
                    "risk_on_count": statuses.count("RISK_ON"),
                    "reason": "; ".join(detail.get("reason", pd.Series(dtype=str)).dropna().astype(str).tolist()),
                }
            ]
        )

    def _write_report(self, detail: pd.DataFrame, summary: pd.DataFrame) -> None:
        row = summary.iloc[0] if not summary.empty else {}
        lines = [
            "# Market Environment Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            f"- Market status: {row.get('market_status', 'NO_DATA')}",
            f"- Recommended action: {row.get('recommended_action', 'OBSERVE_ONLY')}",
            f"- Reason: {row.get('reason', '')}",
            "",
            "| symbol | status | close | ma50 | ma200 | return_5d | realized_vol_20d | reason |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in detail.to_dict(orient="records"):
            lines.append(
                f"| {item.get('symbol', '')} | {item.get('status', '')} | {item.get('close', '')} | "
                f"{item.get('ma50', '')} | {item.get('ma200', '')} | {item.get('return_5d', '')} | "
                f"{item.get('realized_vol_20d', '')} | {item.get('reason', '')} |"
            )
        (self.output_dir / "market_environment_report.md").write_text("\n".join(lines), encoding="utf-8")
