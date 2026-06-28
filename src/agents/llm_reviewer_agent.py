from __future__ import annotations

import json

from src.agents.base import Agent, AgentContext, AgentResult, read_csv
from src.agents.llm_client import OpenRouterClient


class LLMReviewerAgent(Agent):
    """调用 OpenRouter 大模型，生成中文管理层分析。"""

    name = "LLMReviewerAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        client = OpenRouterClient()
        if not client.configured:
            details = {"configured": False, "output_file": ""}
            context.artifacts["llm_review"] = details
            return AgentResult(self.name, "SKIP", "未设置 OPENROUTER_API_KEY，已跳过 LLM 分析", details)

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
        return AgentResult(self.name, "OK", "OpenRouter LLM 管理层分析已生成", details)

    def _build_payload(self, context: AgentContext) -> dict[str, object]:
        return {
            "task": "请作为金融模拟盘 Overall Manager，审查本地模拟盘和研究结果。",
            "hard_rules": [
                "不得建议真实下单",
                "不得建议杠杆、做空、期权",
                "必须强调这是模拟盘和研究系统",
                "结论要可执行，但不能承诺赚钱",
            ],
            "manager_artifacts": context.artifacts,
            "local_report": self._frame_tail(context.output_dir / context.local_config.local_report_file),
            "positions": self._frame_tail(context.output_dir / context.local_config.positions_file),
            "decisions": self._frame_tail(context.output_dir / context.local_config.decision_log_file),
            "candidate_rank": self._frame_head(context.output_dir / "candidate_rank.csv"),
            "no_trade_summary": self._frame_tail(context.output_dir / "no_trade_summary.csv"),
            "allocation": self._frame_tail(context.output_dir / "portfolio_allocation.csv"),
            "universe_summary": self._frame_tail(context.output_dir / "universe_summary.csv"),
            "universe_filter": self._frame_tail(context.output_dir / "universe_filter.csv"),
            "factor_lab_summary": self._frame_tail(context.output_dir / "factor_lab_summary.csv"),
            "factor_lab_latest_rank": self._frame_tail(context.output_dir / "factor_lab_latest_rank.csv"),
            "agent_log": self._frame_tail(context.output_dir / "agent_run_log.csv"),
        }

    @staticmethod
    def _frame_tail(path) -> list[dict[str, object]]:
        frame = read_csv(path)
        if frame.empty:
            return []
        return frame.tail(10).fillna("").to_dict(orient="records")

    @staticmethod
    def _frame_head(path) -> list[dict[str, object]]:
        frame = read_csv(path)
        if frame.empty:
            return []
        return frame.head(10).fillna("").to_dict(orient="records")

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是一个谨慎的量化交易模拟盘 Overall Manager。"
            "你只分析本地模拟盘、回测、风控、研究报告，不允许真实交易。"
            "请用中文输出，结构包括：总体结论、风险状态、策略观察、组合建议、下一步动作。"
            "不要承诺收益，不要建议用户加杠杆、做空或交易期权。"
        )
