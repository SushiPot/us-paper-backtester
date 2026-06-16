from __future__ import annotations

import traceback

from src.allocation_optimizer import PortfolioAllocationOptimizer
from src.config import BacktestConfig, LocalPaperConfig
from src.performance import PerformanceReportBuilder
from src.strategy_health import StrategyHealthAnalyzer
from src.walk_forward import WalkForwardValidator


def main() -> None:
    """研究辅助入口：刷新绩效报告和组合权重建议，不下单。"""
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
        print("本地模拟盘绩效报告已更新")
        print(f"夏普比率: {local_summary.sharpe_ratio:.2f}")
        print(f"最大回撤: {local_summary.max_drawdown:.2%}")
    else:
        print("本地模拟盘资金曲线不足，暂未生成绩效报告")

    print("组合权重建议已更新")
    print(f"方法: {allocation_summary.method}")
    print(f"股票仓位: {allocation_summary.stock_weight:.2%}")
    print(f"现金仓位: {allocation_summary.cash_weight:.2%}")
    print("Walk-forward 验证已更新")
    print(f"稳定性评分: {walk_forward_summary.stability_score:.2f}")
    print(f"建议参数: {walk_forward_summary.recommended_params_label}")
    print(f"建议动作: {walk_forward_summary.recommended_action}")
    print("策略健康度已更新")
    print(f"总评分: {health_summary.overall_score:.2f}")
    print(f"状态: {health_summary.health_status}")
    print(f"建议动作: {health_summary.recommended_action}")
    print("输出目录: outputs")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] research_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
