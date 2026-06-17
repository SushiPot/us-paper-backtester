from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentResult
from src.github_project_discovery import GitHubProjectDiscovery


class GitHubDiscoveryAgent(Agent):
    """联网搜索 GitHub 候选项目并排序。"""

    name = "GitHubDiscoveryAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        frame = GitHubProjectDiscovery(context.output_dir).run()
        top_repo = str(frame.iloc[0]["repo"]) if not frame.empty else ""
        details = {
            "candidate_count": int(len(frame)),
            "top_repo": top_repo,
            "output": "outputs/github_project_candidates.csv",
        }
        context.artifacts["github_discovery"] = details
        return AgentResult(self.name, "OK", "GitHub 候选项目搜索完成", details)
