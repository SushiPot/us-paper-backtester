from __future__ import annotations

from pathlib import Path

import pandas as pd

from .agents.base import read_csv
from .adaptive_config import write_adaptive_profile
from .database import get_store


class SelfOptimizationReporter:
    """汇总所有研究输出，生成下一步自主优化建议。"""

    def __init__(self, output_dir: Path = Path("outputs")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        health = read_csv(self.output_dir / "strategy_health.csv")
        walk_forward = read_csv(self.output_dir / "walk_forward_summary.csv")
        variants = read_csv(self.output_dir / "strategy_variant_scores.csv")
        github = read_csv(self.output_dir / "github_project_candidates.csv")
        decisions = read_csv(self.output_dir / "decision_log.csv")
        positions = read_csv(self.output_dir / "positions.csv")

        actions = []
        actions.extend(self._strategy_actions(health, walk_forward, variants))
        actions.extend(self._operation_actions(decisions, positions))
        actions.extend(self._github_actions(github))

        frame = pd.DataFrame(actions)
        if not frame.empty:
            frame = frame.sort_values(["priority", "score"], ascending=[True, False])
        profile = write_adaptive_profile(self.output_dir)
        frame.to_csv(self.output_dir / "self_optimization_actions.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame, health, walk_forward, variants, github, profile)
        get_store().append_generic_frame("self_optimization_actions", "self_optimization_actions.csv", frame)
        return frame

    @staticmethod
    def _strategy_actions(health: pd.DataFrame, walk_forward: pd.DataFrame, variants: pd.DataFrame) -> list[dict[str, object]]:
        actions = []
        if not variants.empty:
            best = variants.iloc[0]
            actions.append(
                {
                    "priority": 1,
                    "category": "strategy",
                    "action": f"Keep evaluating variant: {best['variant']}",
                    "rationale": (
                        f"Variant score {float(best['variant_score']):.2f}, "
                        f"return {float(best['total_return']):.2%}, "
                        f"drawdown {float(best['max_drawdown']):.2%}."
                    ),
                    "score": float(best["variant_score"]),
                    "status": "RECOMMENDED",
                }
            )
        if not walk_forward.empty:
            row = walk_forward.iloc[-1]
            stability = float(row.get("stability_score", 0.0))
            action = "Keep walk-forward gate active" if stability >= 60 else "Do not increase risk until walk-forward improves"
            actions.append(
                {
                    "priority": 1,
                    "category": "validation",
                    "action": action,
                    "rationale": f"Walk-forward stability score is {stability:.2f}.",
                    "score": stability,
                    "status": "ACTIVE_GATE",
                }
            )
        if not health.empty:
            row = health.iloc[-1]
            recommended = str(row.get("recommended_action", ""))
            actions.append(
                {
                    "priority": 1,
                    "category": "risk",
                    "action": f"Respect health gate: {recommended}",
                    "rationale": str(row.get("reason", "")),
                    "score": float(row.get("overall_score", 0.0)),
                    "status": "ACTIVE_GATE",
                }
            )
        return actions

    @staticmethod
    def _operation_actions(decisions: pd.DataFrame, positions: pd.DataFrame) -> list[dict[str, object]]:
        actions = []
        if not decisions.empty and "reject_reason" in decisions.columns:
            recent = decisions.tail(100)
            reject_rate = float(recent["reject_reason"].fillna("").astype(str).str.len().gt(0).mean())
            actions.append(
                {
                    "priority": 2,
                    "category": "diagnostics",
                    "action": "Monitor rejected signal reasons",
                    "rationale": f"Recent reject/explanation rate is {reject_rate:.0%}; explanations are now available in decision_log.csv.",
                    "score": round((1 - reject_rate) * 100, 2),
                    "status": "MONITOR",
                }
            )
        if not positions.empty:
            actions.append(
                {
                    "priority": 2,
                    "category": "portfolio",
                    "action": "Track open paper positions before adding more signals",
                    "rationale": f"Open positions: {len(positions)}.",
                    "score": 60.0,
                    "status": "MONITOR",
                }
            )
        return actions

    @staticmethod
    def _github_actions(github: pd.DataFrame) -> list[dict[str, object]]:
        actions = []
        if github.empty:
            actions.append(
                {
                    "priority": 3,
                    "category": "github",
                    "action": "Run online manager to refresh GitHub candidates",
                    "rationale": "No GitHub candidates are available yet.",
                    "score": 0.0,
                    "status": "NEEDS_DATA",
                }
            )
            return actions

        for _, row in github.head(5).iterrows():
            actions.append(
                {
                    "priority": 3,
                    "category": f"github:{row.get('category', '')}",
                    "action": f"Evaluate {row.get('repo', '')}",
                    "rationale": f"{row.get('reason', '')} Suggested action: {row.get('suggested_action', '')}.",
                    "score": float(row.get("integration_score", 0.0)),
                    "status": str(row.get("suggested_action", "WATCH_ONLY")),
                }
            )
        return actions

    def _write_report(
        self,
        actions: pd.DataFrame,
        health: pd.DataFrame,
        walk_forward: pd.DataFrame,
        variants: pd.DataFrame,
        github: pd.DataFrame,
        profile: dict[str, object],
    ) -> None:
        lines = [
            "# Self Optimization Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "## Current Gates",
            "",
        ]
        if not health.empty:
            row = health.iloc[-1]
            lines.append(f"- Health: {row.get('overall_score', '')} / {row.get('health_status', '')} / {row.get('recommended_action', '')}")
        if not walk_forward.empty:
            row = walk_forward.iloc[-1]
            lines.append(f"- Walk-forward: {row.get('stability_score', '')} / {row.get('recommended_action', '')}")
        if not variants.empty:
            row = variants.iloc[0]
            lines.append(f"- Best variant: {row.get('variant', '')} score={row.get('variant_score', '')}")
        lines.append(
            f"- Adaptive profile: {profile.get('profile_name', '')} / {profile.get('gate_status', '')} / {profile.get('reason', '')}"
        )
        lines.extend(["", "## Recommended Actions", ""])
        if actions.empty:
            lines.append("No actions generated.")
        else:
            columns = ["priority", "category", "action", "score", "status", "rationale"]
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in actions.to_dict(orient="records"):
                lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
        if not github.empty:
            lines.extend(["", "## GitHub Candidate Snapshot", ""])
            for _, row in github.head(10).iterrows():
                lines.append(f"- {row.get('repo', '')}: {row.get('suggested_action', '')}, score={row.get('integration_score', '')}")
        (self.output_dir / "self_optimization_report.md").write_text("\n".join(lines), encoding="utf-8")
