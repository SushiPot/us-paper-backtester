from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from src.agents.base import AgentContext, AgentResult, append_agent_log
from src.agents.llm_reviewer_agent import LLMReviewerAgent
from src.agents.github_discovery_agent import GitHubDiscoveryAgent
from src.agents.factor_lab_agent import FactorLabAgent
from src.agents.local_paper_agent import LocalPaperAgent
from src.agents.market_data_agent import MarketDataAgent
from src.agents.notification_agent import NotificationAgent
from src.agents.online_research_agent import OnlineResearchAgent
from src.agents.report_agent import ReportAgent
from src.agents.research_agent import ResearchAgent
from src.agents.risk_agent import RiskAgent
from src.agents.self_optimization_agent import SelfOptimizationAgent


class AgentMode(str, Enum):
    """Manager 运行模式。"""

    LOCAL = "local"
    ONLINE = "online"
    AI = "ai"


@dataclass(frozen=True)
class ManagerRunConfig:
    """Overall Manager 的运行开关。"""

    mode: AgentMode = AgentMode.LOCAL
    run_local_paper: bool = True
    run_research: bool = True
    run_online_research: bool = False
    run_llm_review: bool = False
    stop_on_error: bool = False

    @classmethod
    def for_mode(
        cls,
        mode: str | AgentMode,
        run_local_paper: bool = True,
        run_research: bool = True,
        stop_on_error: bool = False,
    ) -> "ManagerRunConfig":
        agent_mode = mode if isinstance(mode, AgentMode) else AgentMode(mode)
        return cls(
            mode=agent_mode,
            run_local_paper=run_local_paper,
            run_research=run_research,
            run_online_research=agent_mode in {AgentMode.ONLINE, AgentMode.AI},
            run_llm_review=agent_mode is AgentMode.AI,
            stop_on_error=stop_on_error,
        )


class OverallManager:
    """总控 Agent，调度多个子 Agent 协作。"""

    def __init__(self, config: ManagerRunConfig | None = None) -> None:
        self.config = config or ManagerRunConfig()

    def run_once(self) -> list[AgentResult]:
        print(f"[START] OverallManager.run_once 已进入 mode={self.config.mode.value}", flush=True)
        context = AgentContext()
        context.output_dir.mkdir(parents=True, exist_ok=True)
        context.artifacts["manager_started_at"] = pd.Timestamp.now()

        agents = [MarketDataAgent()]
        if self.config.run_online_research:
            agents.append(OnlineResearchAgent())
            agents.append(GitHubDiscoveryAgent())
        if self.config.run_local_paper:
            agents.append(LocalPaperAgent())
        if self.config.run_research:
            agents.append(FactorLabAgent())
            agents.append(ResearchAgent())
            agents.append(SelfOptimizationAgent())
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
        notification_result = NotificationAgent().run(context)
        results.append(notification_result)
        append_agent_log(context.output_dir, results)

        print("[END] OverallManager.run_once 正常结束", flush=True)
        return results
