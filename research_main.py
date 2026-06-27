from __future__ import annotations

import traceback

from src.allocation_optimizer import PortfolioAllocationOptimizer
from src.config import BacktestConfig, LocalPaperConfig
from src.performance import PerformanceReportBuilder
from src.strategy_health import StrategyHealthAnalyzer
from src.walk_forward import WalkForwardValidator


def main() -> None:
    """?????????????????????????"""
    local_config = LocalPaperConfig()
    backtest_config = BacktestConfig()

    report_builder = PerformanceReportBuilder(local_config.output_dir)
    local_summary = report_builder.build_from_equity_csv(
        local_config.account_history_file,
        local_config.local_performance_report_file,
        local_config.local_performance_metrics_file,
        "Local Paper Trading Performance Report",
    )

    allocation_summary = PortfolioAllocationOptimizer(backtest_config, target_equity=local_config.initial_cash).run()
    walk_forward_summary = WalkForwardValidator(backtest_config, output_dir=local_config.output_dir).run()
    health_summary = StrategyHealthAnalyzer(local_config, backtest_config).run()

    if local_summary:
        print("????????????")
        print(f"????: {local_summary.sharpe_ratio:.2f}")
        print(f"????: {local_summary.max_drawdown:.2%}")
    else:
        print("????????????????????")

    print("?????????")
    print(f"??: {allocation_summary.method}")
    print(f"????: {allocation_summary.stock_weight:.2%}")
    print(f"????: {allocation_summary.cash_weight:.2%}")
    print("Walk-forward ?????")
    print(f"?????: {walk_forward_summary.stability_score:.2f}")
    print(f"????: {walk_forward_summary.recommended_params_label}")
    print(f"????: {walk_forward_summary.recommended_action}")
    print("????????")
    print(f"???: {health_summary.overall_score:.2f}")
    print(f"??: {health_summary.health_status}")
    print(f"????: {health_summary.recommended_action}")
    print("????: outputs")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] research_main.py ????: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
