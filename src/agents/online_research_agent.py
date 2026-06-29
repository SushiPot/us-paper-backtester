from __future__ import annotations

from dataclasses import dataclass
from time import sleep

import pandas as pd
import requests

from src.agents.base import Agent, AgentContext, AgentResult
from src.credentials import get_github_token


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
    FALLBACK_STATS = {
        "microsoft/qlib": {"stars": 45183, "forks": 7192},
        "nautechsystems/nautilus_trader": {"stars": 24232, "forks": 3072},
        "mementum/backtrader": {"stars": 22127, "forks": 5150},
        "QuantConnect/Lean": {"stars": 20193, "forks": 4984},
        "kernc/backtesting.py": {"stars": 8567, "forks": 1478},
        "polakowo/vectorbt": {"stars": 8047, "forks": 1035},
        "ranaroussi/quantstats": {"stars": 7334, "forks": 1200},
        "PyPortfolio/PyPortfolioOpt": {"stars": 5808, "forks": 1139},
        "dcajasn/Riskfolio-Lib": {"stars": 4296, "forks": 677},
        "pmorissette/bt": {"stars": 2897, "forks": 485},
        "skfolio/skfolio": {"stars": 2034, "forks": 211},
        "Lumiwealth/lumibot": {"stars": 1697, "forks": 329},
    }

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
        cached_rows = self._cached_rows_by_repo(context.output_dir / "online_research_projects.csv")
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
                        "metadata_source": "live",
                        "fetch_error": "",
                    }
                )
            except Exception as exc:
                errors.append(f"{project.repo}: {type(exc).__name__}: {exc}")
                cached = cached_rows.get(project.repo)
                if cached:
                    fallback_stats = self.FALLBACK_STATS.get(project.repo, {})
                    if int(float(cached.get("stars", 0) or 0)) <= 0:
                        cached["stars"] = fallback_stats.get("stars", 0)
                    if int(float(cached.get("forks", 0) or 0)) <= 0:
                        cached["forks"] = fallback_stats.get("forks", 0)
                    cached["metadata_source"] = "cached_after_error"
                    cached["fetch_error"] = f"{type(exc).__name__}: {exc}"
                    rows.append(cached)
                else:
                    rows.append(self._fallback_row(project, f"{type(exc).__name__}: {exc}"))

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
            "used_fallback": not cached_rows and bool(errors),
            "used_cached_rows": bool(cached_rows) and bool(errors),
        }
        context.artifacts["online_research"] = details
        status = "WARN" if errors else "OK"
        message = "联网公开项目扫描完成" if not errors else "联网扫描受限，已用缓存补齐可用项目"
        return AgentResult(self.name, status, message, details)

    @staticmethod
    def _fetch_repo(repo: str) -> dict:
        url = f"https://api.github.com/repos/{repo}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "us-paper-backtester-online-agent",
        }
        token = _github_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        last_error: Exception | None = None
        for attempt in range(1, OnlineResearchAgent.retry_count + 1):
            try:
                response = requests.get(url, headers=headers, timeout=20)
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                response = getattr(exc, "response", None)
                if response is not None and 400 <= response.status_code < 500 and response.status_code != 429:
                    break
                if attempt < OnlineResearchAgent.retry_count:
                    sleep(OnlineResearchAgent.retry_wait_seconds * attempt)
        raise RuntimeError(f"GitHub request failed after {OnlineResearchAgent.retry_count} attempts: {last_error}")

    @staticmethod
    def _cached_rows_by_repo(path) -> dict[str, dict[str, object]]:
        if not path.exists() or path.stat().st_size == 0:
            return {}
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return {}
        if frame.empty or "repo" not in frame.columns:
            return {}
        rows = {}
        for row in frame.to_dict(orient="records"):
            repo = str(row.get("repo", "")).strip()
            if repo:
                rows[repo] = row
        return rows

    def _fallback_rows(self) -> list[dict[str, object]]:
        rows = []
        for project in self.PROJECTS:
            rows.append(self._fallback_row(project, ""))
        return rows

    @staticmethod
    def _fallback_row(project: GitHubProject, fetch_error: str) -> dict[str, object]:
        fallback_stats = OnlineResearchAgent.FALLBACK_STATS.get(project.repo, {})
        return {
            "name": project.name,
            "repo": project.repo,
            "description": "GitHub API unavailable or rate limited; fallback metadata only.",
            "stars": fallback_stats.get("stars", 0),
            "forks": fallback_stats.get("forks", 0),
            "open_issues": 0,
            "updated_at": "",
            "html_url": f"https://github.com/{project.repo}",
            "category": project.category,
            "use_now": project.use_now,
            "avoid_now": project.avoid_now,
            "metadata_source": "fallback",
            "fetch_error": fetch_error,
        }


def _github_token() -> str:
    """优先用环境变量或本地文件；没有时复用本机 gh 登录 token。"""
    return get_github_token()
