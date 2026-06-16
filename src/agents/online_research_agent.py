from __future__ import annotations

from dataclasses import dataclass
import os

import pandas as pd
import requests

from src.agents.base import Agent, AgentContext, AgentResult


@dataclass(frozen=True)
class GitHubProject:
    """联网练习模式关注的开源项目。"""

    name: str
    repo: str
    reason: str


class OnlineResearchAgent(Agent):
    """联网读取公开 GitHub 元数据，不触碰交易账户。"""

    name = "OnlineResearchAgent"

    PROJECTS = [
        GitHubProject("QuantStats", "ranaroussi/quantstats", "绩效分析和风险指标"),
        GitHubProject("PyPortfolioOpt", "PyPortfolio/PyPortfolioOpt", "组合优化和目标权重"),
        GitHubProject("Riskfolio-Lib", "dcajasn/Riskfolio-Lib", "风险平价、CVaR 和更专业的组合风险优化"),
        GitHubProject("skfolio", "skfolio/skfolio", "scikit-learn 风格组合优化和模型选择"),
        GitHubProject("vectorbt", "polakowo/vectorbt", "参数扫描和向量化回测"),
        GitHubProject("backtesting.py", "kernc/backtesting.py", "简洁事件式回测框架参考"),
        GitHubProject("bt", "pmorissette/bt", "组合回测和资产配置框架参考"),
        GitHubProject("FinRL", "AI4Finance-Foundation/FinRL", "强化学习交易实验，适合研究模式"),
        GitHubProject("Qlib", "microsoft/qlib", "机器学习量化研究平台"),
        GitHubProject("LangGraph", "langchain-ai/langgraph", "长期运行 Agent 工作流"),
        GitHubProject("CrewAI", "crewAIInc/crewAI", "多角色 Agent 协作原型"),
    ]

    def _run(self, context: AgentContext) -> AgentResult:
        rows = []
        errors = []
        for project in self.PROJECTS:
            try:
                payload = self._fetch_repo(project.repo)
                rows.append(
                    {
                        "name": project.name,
                        "repo": project.repo,
                        "description": payload.get("description", ""),
                        "stars": int(payload.get("stargazers_count", 0)),
                        "forks": int(payload.get("forks_count", 0)),
                        "open_issues": int(payload.get("open_issues_count", 0)),
                        "updated_at": payload.get("updated_at", ""),
                        "html_url": payload.get("html_url", f"https://github.com/{project.repo}"),
                        "reason": project.reason,
                    }
                )
            except Exception as exc:
                errors.append(f"{project.repo}: {type(exc).__name__}: {exc}")

        if not rows:
            rows = self._fallback_rows()

        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values(["stars", "updated_at"], ascending=[False, False])
            frame.to_csv(context.output_dir / "online_research_projects.csv", index=False, encoding="utf-8-sig")

        details = {
            "project_count": len(rows),
            "error_count": len(errors),
            "errors": errors,
            "top_project": str(frame.iloc[0]["repo"]) if not frame.empty else "",
            "used_fallback": bool(errors),
        }
        context.artifacts["online_research"] = details
        status = "WARN" if errors else "OK"
        message = "联网公开项目扫描完成" if not errors else "联网扫描受限，已写入降级候选项目清单"
        return AgentResult(self.name, status, message, details)

    @staticmethod
    def _fetch_repo(repo: str) -> dict:
        url = f"https://api.github.com/repos/{repo}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "us-paper-backtester-online-agent",
        }
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()

    def _fallback_rows(self) -> list[dict[str, object]]:
        rows = []
        for project in self.PROJECTS:
            rows.append(
                {
                    "name": project.name,
                    "repo": project.repo,
                    "description": "GitHub API unavailable or rate limited; fallback metadata only.",
                    "stars": 0,
                    "forks": 0,
                    "open_issues": 0,
                    "updated_at": "",
                    "html_url": f"https://github.com/{project.repo}",
                    "reason": project.reason,
                }
            )
        return rows
