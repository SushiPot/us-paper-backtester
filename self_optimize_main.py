from __future__ import annotations

import traceback

from src.github_project_discovery import GitHubProjectDiscovery
from src.self_optimizer import SelfOptimizationReporter
from src.strategy_variant_evaluator import StrategyVariantEvaluator


def main() -> None:
    """运行自我优化评估：策略变体、GitHub候选和行动建议。"""
    variants = StrategyVariantEvaluator().run()
    github = GitHubProjectDiscovery().run()
    actions = SelfOptimizationReporter().run()
    best_variant = str(variants.iloc[0]["variant"]) if not variants.empty else "none"
    top_repo = str(github.iloc[0]["repo"]) if not github.empty else "none"
    top_action = str(actions.iloc[0]["action"]) if not actions.empty else "none"
    print("自我优化评估完成")
    print(f"最佳策略变体: {best_variant}")
    print(f"GitHub首选候选: {top_repo}")
    print(f"首要行动: {top_action}")
    print("输出文件:")
    print("- outputs/strategy_variant_scores.csv")
    print("- outputs/github_project_candidates.csv")
    print("- outputs/self_optimization_actions.csv")
    print("- outputs/self_optimization_report.md")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] self_optimize_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
