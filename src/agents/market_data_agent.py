from __future__ import annotations

import time

from src.agents.base import Agent, AgentContext, AgentResult


class MarketDataAgent(Agent):
    """???????????????????"""

    name = "MarketDataAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        cache_dir = context.backtest_config.cache_dir
        stale_symbols = []
        missing_symbols = []
        latest_cache_times = {}
        max_age_seconds = context.backtest_config.cache_max_age_hours * 60 * 60

        for symbol in context.backtest_config.symbols:
            path = cache_dir / f"{symbol}.csv"
            if not path.exists():
                missing_symbols.append(symbol)
                continue

            age_seconds = time.time() - path.stat().st_mtime
            latest_cache_times[symbol] = round(age_seconds / 3600, 2)
            if age_seconds > max_age_seconds:
                stale_symbols.append(symbol)

        context.artifacts["market_data"] = {
            "missing_symbols": missing_symbols,
            "stale_symbols": stale_symbols,
            "cache_age_hours": latest_cache_times,
        }

        if missing_symbols:
            return AgentResult(self.name, "WARN", f"??????: {', '.join(missing_symbols)}", context.artifacts["market_data"])
        if stale_symbols:
            return AgentResult(self.name, "WARN", f"????????: {', '.join(stale_symbols)}", context.artifacts["market_data"])
        return AgentResult(self.name, "OK", "???????????????", context.artifacts["market_data"])
