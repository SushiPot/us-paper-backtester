from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentResult
from src.config import BacktestConfig
from src.data import MarketDataLoader
from src.factor_lab import FactorLabAnalyzer
from src.indicators import add_indicators


class FactorLabAgent(Agent):
    """刷新轻量因子实验室，评估因子质量而不是直接下单。"""

    name = "FactorLabAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        data_config = BacktestConfig(
            symbols=context.local_config.symbols,
            start_date=context.local_config.historical_start_date,
            output_dir=context.output_dir,
            retry_count=context.local_config.retry_count,
            retry_wait_seconds=context.local_config.retry_wait_seconds,
        )
        raw_data = MarketDataLoader(data_config).download_all()
        market_data = {
            symbol: add_indicators(
                frame,
                context.local_config.fast_ma,
                context.local_config.slow_ma,
                context.local_config.rsi_period,
            )
            for symbol, frame in raw_data.items()
        }
        summary = FactorLabAnalyzer(context.local_config, context.output_dir).run(market_data)
        leader = summary.iloc[0].to_dict() if not summary.empty else {}
        details = {
            "factor_count": int(summary["factor_name"].nunique()) if not summary.empty else 0,
            "rows": int(len(summary)),
            "leader_factor": str(leader.get("factor_name", "")),
            "leader_score": float(leader.get("factor_score", 0.0) or 0.0),
            "leader_status": str(leader.get("status", "")),
            "output_file": str(context.output_dir / "factor_lab_summary.csv"),
        }
        context.artifacts["factor_lab"] = details
        if not summary.empty and str(leader.get("status", "")) in {"LEADING", "OBSERVE"}:
            return AgentResult(self.name, "OK", f"因子实验室已刷新，领先因子: {details['leader_factor']}", details)
        return AgentResult(self.name, "WARN", "因子实验室已刷新，但暂无强因子", details)
