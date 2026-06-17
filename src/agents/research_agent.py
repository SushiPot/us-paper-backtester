from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentResult, read_csv
from src.allocation_optimizer import PortfolioAllocationOptimizer
from src.performance import PerformanceReportBuilder
from src.strategy_health import StrategyHealthAnalyzer
from src.walk_forward import WalkForwardValidator


class ResearchAgent(Agent):
    """刷新绩效报告和组合权重建议。"""

    name = "ResearchAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        report_builder = PerformanceReportBuilder(context.output_dir)
        performance = report_builder.build_from_equity_csv(
            context.local_config.account_history_file,
            context.local_config.local_performance_report_file,
            context.local_config.local_performance_metrics_file,
            "Local Paper Trading Performance Report",
        )
        allocation = PortfolioAllocationOptimizer(
            context.backtest_config,
            output_dir=context.output_dir,
            target_equity=context.local_config.initial_cash,
        ).run()
        walk_forward = WalkForwardValidator(context.backtest_config, output_dir=context.output_dir).run()
        health = StrategyHealthAnalyzer(context.local_config, context.backtest_config).run()

        allocation_frame = read_csv(context.output_dir / "portfolio_allocation.csv")
        details = {
            "performance_report_created": performance is not None,
            "allocation_method": allocation.method,
            "stock_weight": allocation.stock_weight,
            "cash_weight": allocation.cash_weight,
            "allocation_rows": len(allocation_frame),
            "walk_forward_score": walk_forward.stability_score,
            "strategy_health_score": health.overall_score,
            "strategy_health_status": health.health_status,
        }
        if performance:
            details["performance_sharpe"] = performance.sharpe_ratio
            details["performance_max_drawdown"] = performance.max_drawdown

        context.artifacts["research"] = details
        return AgentResult(self.name, "OK", "研究报告和组合权重建议已刷新", details)
