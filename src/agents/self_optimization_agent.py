from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentResult
from src.self_optimizer import SelfOptimizationReporter
from src.strategy_variant_evaluator import StrategyVariantEvaluator


class SelfOptimizationAgent(Agent):
    """自动评估策略变体并生成下一步优化建议。"""

    name = "SelfOptimizationAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        variants = StrategyVariantEvaluator(context.backtest_config, context.output_dir).run()
        actions = SelfOptimizationReporter(context.output_dir).run()
        best_variant = str(variants.iloc[0]["variant"]) if not variants.empty else ""
        top_action = str(actions.iloc[0]["action"]) if not actions.empty else ""
        details = {
            "variant_count": int(len(variants)),
            "best_variant": best_variant,
            "action_count": int(len(actions)),
            "top_action": top_action,
            "report": "outputs/self_optimization_report.md",
        }
        context.artifacts["self_optimization"] = details
        return AgentResult(self.name, "OK", "自我优化报告已生成", details)
