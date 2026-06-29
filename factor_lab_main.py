from __future__ import annotations

import traceback

from src.config import BacktestConfig, LocalPaperConfig
from src.data import MarketDataLoader
from src.factor_lab import FactorLabAnalyzer
from src.indicators import add_indicators
from src.universe import UniverseFilter, filter_market_data_for_tradable


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        import pandas as pd

        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def main() -> None:
    """单独运行轻量因子实验室，不连接券商，不下单。"""
    config = LocalPaperConfig()
    data_config = BacktestConfig(
        symbols=config.symbols,
        start_date=config.historical_start_date,
        output_dir=config.output_dir,
        retry_count=config.retry_count,
        retry_wait_seconds=config.retry_wait_seconds,
        max_new_symbol_downloads_per_run=config.max_new_symbol_downloads_per_run,
        market_data_primary_source=config.market_data_primary_source,
        market_data_request_interval_seconds=config.market_data_request_interval_seconds,
    )
    raw_data = MarketDataLoader(data_config).download_all()
    market_data = {
        symbol: add_indicators(frame, config.fast_ma, config.slow_ma, config.rsi_period)
        for symbol, frame in raw_data.items()
    }
    UniverseFilter(config, config.output_dir).run(market_data)
    summary = FactorLabAnalyzer(config, config.output_dir).run(filter_market_data_for_tradable(market_data, config.output_dir))
    print("[OK] Factor Lab 已完成", flush=True)
    if not summary.empty:
        leader = summary.iloc[0]
        print(
            f"[LEADER] {leader.get('factor_name', '')} "
            f"score={_safe_float(leader.get('factor_score', 0.0)):.2f} "
            f"status={leader.get('status', '')}",
            flush=True,
        )
    print("[OUTPUT] outputs/factor_lab_summary.csv", flush=True)
    print("[OUTPUT] outputs/factor_lab_latest_rank.csv", flush=True)
    print("[OUTPUT] outputs/factor_lab_report.md", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] factor_lab_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
