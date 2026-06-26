from __future__ import annotations

from dataclasses import dataclass
import os
from time import sleep

import pandas as pd
import requests

from src.agents.base import Agent, AgentContext, AgentResult


@dataclass(frozen=True)
class GitHubProject:
    """联网练习模式关注的开源项目。"""

    name: str
    repo: str
    category: str
    use_now: str
    avoid_now: str


class OnlineResearchAgent(Agent):
    """联网读取公开 GitHub 元数据，不触碰交易账户。"""

    name = "OnlineResearchAgent"
    retry_count = 3
    retry_wait_seconds = 1.5

    PROJECTS = [
        GitHubProject("Qlib", "microsoft/qlib", "AI/factor research", "学习因子数据集、标签、训练/验证分层流程", "直接引入重型 ML 栈或让模型自动下单"),
        GitHubProject("NautilusTrader", "nautechsystems/nautilus_trader", "event-driven engine", "学习确定性事件、订单/成交/风控边界", "接入真实交易网关或加密货币模块"),
        GitHubProject("backtrader", "mementum/backtrader", "backtesting architecture", "学习 broker、strategy、feed 分离", "迁移到已经停止活跃的整套框架"),
        GitHubProject("LEAN", "QuantConnect/Lean", "institutional engine", "学习股票/期权/组合/风控模型边界", "复制大型引擎或启用真实券商接口"),
        GitHubProject("backtesting.py", "kernc/backtesting.py", "lightweight backtesting", "学习简洁策略接口和结果可视化", "替换当前本地模拟盘状态机"),
        GitHubProject("vectorbt", "polakowo/vectorbt", "vectorized research", "学习向量化参数扫描和信号矩阵", "把研究结果未经走样验证直接用于交易"),
        GitHubProject("QuantStats", "ranaroussi/quantstats", "performance analytics", "学习收益、回撤、风险报告格式", "只看收益率忽略样本量和回撤"),
        GitHubProject("PyPortfolioOpt", "PyPortfolio/PyPortfolioOpt", "portfolio optimization", "继续用于长仓、无杠杆配置建议", "用优化器输出直接覆盖交易风控"),
        GitHubProject("Riskfolio-Lib", "dcajasn/Riskfolio-Lib", "portfolio risk models", "学习风险平价、CVaR、风险预算", "安装失败时阻塞主程序"),
        GitHubProject("bt", "pmorissette/bt", "portfolio strategy blocks", "学习组合层信号/权重/再平衡组件", "引入过多抽象导致本地流程变复杂"),
        GitHubProject("skfolio", "skfolio/skfolio", "portfolio model validation", "学习组合模型交叉验证和稳健性评估", "过早追求复杂模型"),
        GitHubProject("Lumibot", "Lumiwealth/lumibot", "broker abstraction", "学习券商适配器边界", "接入真实账户或保存敏感凭证"),
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
                        "category": project.category,
                        "use_now": project.use_now,
                        "avoid_now": project.avoid_now,
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
        last_error: Exception | None = None
        for attempt in range(1, OnlineResearchAgent.retry_count + 1):
            try:
                response = requests.get(url, headers=headers, timeout=20)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt < OnlineResearchAgent.retry_count:
                    sleep(OnlineResearchAgent.retry_wait_seconds * attempt)
        raise RuntimeError(f"GitHub request failed after {OnlineResearchAgent.retry_count} attempts: {last_error}")

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
                    "category": project.category,
                    "use_now": project.use_now,
                    "avoid_now": project.avoid_now,
                }
            )
        return rows
