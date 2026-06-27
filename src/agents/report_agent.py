from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.agents.base import Agent, AgentContext, AgentResult


class ReportAgent(Agent):
    """????? Agent ?????? Manager ???"""

    name = "ReportAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        results = context.artifacts.get("agent_results", [])
        report_path = context.output_dir / "manager_report.md"
        report_path.write_text(self._render_report(results), encoding="utf-8")

        details = {
            "report_path": str(report_path),
            "result_count": len(results),
        }
        context.artifacts["manager_report"] = details
        return AgentResult(self.name, "OK", "Manager ?????", details)

    @staticmethod
    def _render_report(results: list[AgentResult]) -> str:
        lines = [
            "# Overall Manager Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "## Agent Results",
            "",
        ]
        for result in results:
            lines.extend(
                [
                    f"### {result.agent}",
                    "",
                    f"- Status: {result.status}",
                    f"- Message: {result.message}",
                    f"- Elapsed Seconds: {result.elapsed_seconds:.2f}",
                    f"- Details: `{result.details}`",
                    "",
                ]
            )

        hard_errors = [result for result in results if result.status == "ERROR"]
        warnings = [result for result in results if result.status == "WARN"]
        lines.extend(
            [
                "## Manager Decision",
                "",
                f"- Hard Errors: {len(hard_errors)}",
                f"- Warnings: {len(warnings)}",
                "- Trading Mode: local simulation only",
                "- Broker Connection: disabled",
                "- Real Orders: forbidden",
                "",
            ]
        )
        if hard_errors:
            lines.append("Manager conclusion: stop and inspect errors before trusting the run.")
        elif warnings:
            lines.append("Manager conclusion: run completed, but warnings require review before changing strategy settings.")
        else:
            lines.append("Manager conclusion: run completed with no hard errors.")
        lines.append("")
        return "\n".join(lines)


def report_exists(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0
