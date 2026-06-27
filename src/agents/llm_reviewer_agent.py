from __future__ import annotations

import json

from src.agents.base import Agent, AgentContext, AgentResult, read_csv
from src.agents.llm_client import OpenRouterClient


class LLMReviewerAgent(Agent):
    """?? OpenRouter ??????????????"""

    name = "LLMReviewerAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        client = OpenRouterClient()
        if not client.configured:
            details = {"configured": False, "output_file": ""}
            context.artifacts["llm_review"] = details
            return AgentResult(self.name, "SKIP", "??? OPENROUTER_API_KEY???? LLM ??", details)

        payload = self._build_payload(context)
        response = client.chat(self._system_prompt(), json.dumps(payload, ensure_ascii=False, indent=2))
        output_path = context.output_dir / "llm_manager_review.md"
        output_path.write_text(response.content, encoding="utf-8")

        details = {
            "configured": True,
            "model": response.model,
            "output_file": str(output_path),
            "content_chars": len(response.content),
        }
        context.artifacts["llm_review"] = details
        return AgentResult(self.name, "OK", "OpenRouter LLM ????????", details)

    def _build_payload(self, context: AgentContext) -> dict[str, object]:
        return {
            "task": "???????? Overall Manager??????????????",
            "hard_rules": [
                "????????",
                "????????????",
                "??????????????",
                "??????????????",
            ],
            "manager_artifacts": context.artifacts,
            "local_report": self._frame_tail(context.output_dir / context.local_config.local_report_file),
            "positions": self._frame_tail(context.output_dir / context.local_config.positions_file),
            "decisions": self._frame_tail(context.output_dir / context.local_config.decision_log_file),
            "allocation": self._frame_tail(context.output_dir / "portfolio_allocation.csv"),
            "agent_log": self._frame_tail(context.output_dir / "agent_run_log.csv"),
        }

    @staticmethod
    def _frame_tail(path) -> list[dict[str, object]]:
        frame = read_csv(path)
        if frame.empty:
            return []
        return frame.tail(10).fillna("").to_dict(orient="records")

    @staticmethod
    def _system_prompt() -> str:
        return (
            "?????????????? Overall Manager?"
            "?????????????????????????????"
            "??????????????????????????????????????"
            "?????????????????????????"
        )
