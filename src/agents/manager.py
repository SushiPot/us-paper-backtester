from __future__ import annotations

from dataclasses import dataclass

from src.agents.base import AgentContext, AgentResult, append_agent_log
from src.agents.llm_reviewer_agent import LLMReviewerAgent
from src.agents.local_paper_agent import LocalPaperAgent
from src.agents.market_data_agent import MarketDataAgent
from src.agents.online_research_agent import OnlineResearchAgent
from src.agents.report_agent import ReportAgent
from src.agents.research_agent import ResearchAgent
from src.agents.risk_agent import RiskAgent


@dataclass(frozen=True)
class ManagerRunConfig:
    """Overall Manager 的运行开关。"""

    run_local_paper: bool = True
    run_research: bool = True
    run_online_research: bool = False
    run_llm_review: bool = False
    stop_on_error: bool = False


class OverallManager:
    """总控 Agent，调度多个子 Agent 协作。"""

    def __init__(self, config: ManagerRunConfig | None = None) -> None:
        self.config = config or ManagerRunConfig()

    def run_once(self) -> list[AgentResult]:
        print("[START] OverallManager.run_once 已进入", flush=True)
        context = AgentContext()
        context.output_dir.mkdir(parents=True, exist_ok=True)

        agents = [MarketDataAgent()]
        if self.config.run_online_research:
            agents.append(OnlineResearchAgent())
        if self.config.run_local_paper:
            agents.append(LocalPaperAgent())
        if self.config.run_research:
            agents.append(ResearchAgent())
        agents.append(RiskAgent())
        if self.config.run_llm_review:
            agents.append(LLMReviewerAgent())

        results: list[AgentResult] = []
        for agent in agents:
            print(f"[AGENT] {agent.name} 开始", flush=True)
            result = agent.run(context)
            results.append(result)
            print(f"[AGENT] {agent.name} {result.status}: {result.message}", flush=True)
            if result.status == "ERROR" and self.config.stop_on_error:
                print("[STOP] 子 Agent 出错，按配置停止后续任务", flush=True)
                break

        context.artifacts["agent_results"] = results
        report_result = ReportAgent().run(context)
        results.append(report_result)
        append_agent_log(context.output_dir, results)

        print("[END] OverallManager.run_once 正常结束", flush=True)
        return results
