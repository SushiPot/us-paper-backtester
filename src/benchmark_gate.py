from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import LocalPaperConfig
from .database import get_store


class BenchmarkGateAnalyzer:
    """比较本地模拟盘和 SPY/QQQ 基准，给新买入风控提供闸门。"""

    def __init__(self, config: LocalPaperConfig | None = None, output_dir: Path = Path("outputs")) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        market_data: dict[str, pd.DataFrame],
        account: dict[str, float | str],
        market_date: pd.Timestamp,
    ) -> pd.DataFrame:
        account_curve = self._account_curve(account, market_date)
        rows = []
        for symbol in self.config.benchmark_symbols:
            benchmark_return = self._benchmark_return(market_data.get(symbol), account_curve)
            local_return = self._local_return(account_curve)
            rows.append(
                {
                    "time": pd.Timestamp.now(),
                    "symbol": symbol,
                    "observation_count": len(account_curve),
                    "local_return": local_return,
                    "benchmark_return": benchmark_return,
                    "excess_return": local_return - benchmark_return,
                }
            )
        detail = pd.DataFrame(rows)
        summary = self._summary(detail)
        detail.to_csv(self.output_dir / "benchmark_gate.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "benchmark_gate_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(detail, summary)
        store = get_store()
        store.append_generic_frame("benchmark_gate", "benchmark_gate.csv", detail)
        store.append_generic_frame("benchmark_gate_summary", "benchmark_gate_summary.csv", summary)
        return summary

    def _account_curve(self, account: dict[str, float | str], market_date: pd.Timestamp) -> pd.Series:
        path = self.output_dir / self.config.account_history_file
        if path.exists() and path.stat().st_size > 0:
            try:
                history = pd.read_csv(path)
            except pd.errors.EmptyDataError:
                history = pd.DataFrame()
        else:
            history = pd.DataFrame()

        rows = []
        if not history.empty and "equity" in history.columns:
            date_column = "market_date" if "market_date" in history.columns else "time"
            for _, row in history.iterrows():
                date = pd.Timestamp(row.get(date_column)).normalize()
                rows.append((date, float(row["equity"])))
        rows.append((pd.Timestamp(market_date).normalize(), float(account.get("equity", 0.0))))
        if not rows:
            return pd.Series(dtype=float)
        frame = pd.DataFrame(rows, columns=["date", "equity"]).dropna()
        return frame.groupby("date")["equity"].last().sort_index()

    @staticmethod
    def _local_return(account_curve: pd.Series) -> float:
        if len(account_curve) < 2:
            return 0.0
        first = float(account_curve.iloc[0])
        return float(account_curve.iloc[-1] / first - 1) if first else 0.0

    @staticmethod
    def _benchmark_return(frame: pd.DataFrame | None, account_curve: pd.Series) -> float:
        if frame is None or frame.empty or len(account_curve) < 2:
            return 0.0
        clean = frame.dropna().sort_index()
        close = clean["close"].astype(float)
        start_date = account_curve.index[0]
        end_date = account_curve.index[-1]
        aligned = close[(close.index >= start_date) & (close.index <= end_date)]
        if len(aligned) < 2:
            return 0.0
        first = float(aligned.iloc[0])
        return float(aligned.iloc[-1] / first - 1) if first else 0.0

    def _summary(self, detail: pd.DataFrame) -> pd.DataFrame:
        if detail.empty:
            return pd.DataFrame(
                [
                    {
                        "time": pd.Timestamp.now(),
                        "status": "NO_DATA",
                        "recommended_action": "OBSERVE_ONLY",
                        "observation_count": 0,
                        "local_return": 0.0,
                        "benchmark_return": 0.0,
                        "excess_return": 0.0,
                        "reason": "no benchmark data",
                    }
                ]
            )
        observation_count = int(detail["observation_count"].max())
        local_return = float(detail["local_return"].mean())
        benchmark_return = float(detail["benchmark_return"].mean())
        excess_return = float(detail["excess_return"].mean())
        status = "OK"
        action = "ALLOW_NORMAL_SIMULATION"
        reason = "local paper is acceptable versus benchmarks"
        if observation_count < self.config.benchmark_gate_min_observations:
            status = "OBSERVATION"
            action = "REDUCE_NEW_BUY_SIZE"
            reason = f"benchmark sample count below {self.config.benchmark_gate_min_observations}"
        elif excess_return <= self.config.benchmark_underperformance_pause_pct and local_return < 0:
            status = "UNDERPERFORMING"
            action = "PAUSE_NEW_BUYS"
            reason = "local paper underperforms benchmarks beyond pause threshold"
        elif excess_return <= self.config.benchmark_underperformance_reduce_pct or local_return < 0:
            status = "LAGGING"
            action = "REDUCE_NEW_BUY_SIZE"
            reason = "local paper is lagging benchmarks or losing money"
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "status": status,
                    "recommended_action": action,
                    "observation_count": observation_count,
                    "local_return": local_return,
                    "benchmark_return": benchmark_return,
                    "excess_return": excess_return,
                    "reason": reason,
                }
            ]
        )

    def _write_report(self, detail: pd.DataFrame, summary: pd.DataFrame) -> None:
        row = summary.iloc[0] if not summary.empty else {}
        lines = [
            "# Benchmark Gate Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            f"- Status: {row.get('status', 'NO_DATA')}",
            f"- Recommended action: {row.get('recommended_action', 'OBSERVE_ONLY')}",
            f"- Local return: {float(row.get('local_return', 0.0)):.2%}",
            f"- Benchmark return: {float(row.get('benchmark_return', 0.0)):.2%}",
            f"- Excess return: {float(row.get('excess_return', 0.0)):.2%}",
            f"- Reason: {row.get('reason', '')}",
            "",
            "| symbol | local_return | benchmark_return | excess_return | observations |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in detail.to_dict(orient="records"):
            lines.append(
                f"| {item.get('symbol', '')} | {float(item.get('local_return', 0.0)):.2%} | "
                f"{float(item.get('benchmark_return', 0.0)):.2%} | "
                f"{float(item.get('excess_return', 0.0)):.2%} | {item.get('observation_count', 0)} |"
            )
        (self.output_dir / "benchmark_gate_report.md").write_text("\n".join(lines), encoding="utf-8")
