from __future__ import annotations

import time

from src.agents.base import Agent, AgentContext, AgentResult


class MarketDataAgent(Agent):
    """检查本地行情缓存的新鲜度，不负责下单。"""

    name = "MarketDataAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        cache_dir = context.backtest_config.cache_dir
        required_symbols = set(getattr(context.backtest_config, "required_symbols", []) or context.backtest_config.symbols)
        missing_required_symbols = []
        missing_optional_symbols = []
        stale_required_symbols = []
        stale_optional_symbols = []
        latest_cache_times = {}
        max_age_seconds = context.backtest_config.cache_max_age_hours * 60 * 60

        for symbol in context.backtest_config.symbols:
            path = cache_dir / f"{symbol}.csv"
            if not path.exists():
                if symbol in required_symbols:
                    missing_required_symbols.append(symbol)
                else:
                    missing_optional_symbols.append(symbol)
                continue

            age_seconds = time.time() - path.stat().st_mtime
            latest_cache_times[symbol] = round(age_seconds / 3600, 2)
            if age_seconds > max_age_seconds:
                if symbol in required_symbols:
                    stale_required_symbols.append(symbol)
                else:
                    stale_optional_symbols.append(symbol)

        context.artifacts["market_data"] = {
            "required_symbols": sorted(required_symbols),
            "missing_symbols": missing_required_symbols,
            "missing_optional_symbols": missing_optional_symbols,
            "stale_symbols": stale_required_symbols,
            "stale_optional_symbols": stale_optional_symbols,
            "cache_age_hours": latest_cache_times,
        }

        if missing_required_symbols:
            return AgentResult(self.name, "WARN", f"缺少核心行情缓存: {', '.join(missing_required_symbols)}", context.artifacts["market_data"])
        if stale_required_symbols:
            return AgentResult(self.name, "WARN", f"核心行情缓存过期: {', '.join(stale_required_symbols)}", context.artifacts["market_data"])
        if missing_optional_symbols:
            return AgentResult(
                self.name,
                "OK",
                f"核心行情缓存正常；扩展股票池还有 {len(missing_optional_symbols)} 个未缓存",
                context.artifacts["market_data"],
            )
        if stale_optional_symbols:
            return AgentResult(
                self.name,
                "OK",
                f"核心行情缓存正常；扩展股票池还有 {len(stale_optional_symbols)} 个缓存过期",
                context.artifacts["market_data"],
            )
        return AgentResult(self.name, "OK", "核心和扩展行情缓存均正常", context.artifacts["market_data"])
