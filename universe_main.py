from __future__ import annotations

import traceback

from src.config import BacktestConfig, LocalPaperConfig
from src.data import MarketDataLoader
from src.universe import UniverseFilter


def main() -> None:
    """单独刷新股票池过滤结果，不连接券商，不下单。"""
    config = LocalPaperConfig()
    data_config = BacktestConfig(
        symbols=config.symbols,
        start_date=config.historical_start_date,
        output_dir=config.output_dir,
        retry_count=config.retry_count,
        retry_wait_seconds=config.retry_wait_seconds,
        max_new_symbol_downloads_per_run=config.max_new_symbol_downloads_per_run,
    )
    raw_data = MarketDataLoader(data_config).download_all()
    frame = UniverseFilter(config, config.output_dir).run(raw_data)
    passed = int(frame["tradable_passed"].map(lambda value: str(value).lower() == "true").sum()) if not frame.empty else 0
    print("[OK] Universe filter 已完成", flush=True)
    print(f"[RESULT] total={len(frame)} tradable_passed={passed}", flush=True)
    print("[OUTPUT] outputs/universe_summary.csv", flush=True)
    print("[OUTPUT] outputs/universe_filter.csv", flush=True)
    print("[OUTPUT] outputs/universe_report.md", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] universe_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
