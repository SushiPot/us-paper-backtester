from __future__ import annotations

from dataclasses import dataclass
import os
from time import sleep

import pandas as pd
import requests

from src.agents.base import Agent, AgentContext, AgentResult


@dataclass(frozen=True)
class GitHubProject:
    """??????????????"""

    name: str
    repo: str
    category: str
    use_now: str
    avoid_now: str


class OnlineResearchAgent(Agent):
    """?????? GitHub ????????????"""

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
        GitHubProject("Qlib", "microsoft/qlib", "AI/factor research", "?????????????/??????", "?????? ML ?????????"),
        GitHubProject("NautilusTrader", "nautechsystems/nautilus_trader", "event-driven engine", "??????????/??/????", "???????????????"),
        GitHubProject("backtrader", "mementum/backtrader", "backtesting architecture", "?? broker?strategy?feed ??", "??????????????"),
        GitHubProject("LEAN", "QuantConnect/Lean", "institutional engine", "????/??/??/??????", "???????????????"),
        GitHubProject("backtesting.py", "kernc/backtesting.py", "lightweight backtesting", "??????????????", "????????????"),
        GitHubProject("vectorbt", "polakowo/vectorbt", "vectorized research", "??????????????", "?????????????????"),
        GitHubProject("QuantStats", "ranaroussi/quantstats", "performance analytics", "??????????????", "?????????????"),
        GitHubProject("PyPortfolioOpt", "PyPortfolio/PyPortfolioOpt", "portfolio optimization", "??????????????", "??????????????"),
        GitHubProject("Riskfolio-Lib", "dcajasn/Riskfolio-Lib", "portfolio risk models", "???????CVaR?????", "??????????"),
        GitHubProject("bt", "pmorissette/bt", "portfolio strategy blocks", "???????/??/?????", "???????????????"),
        GitHubProject("skfolio", "skfolio/skfolio", "portfolio model validation", "????????????????", "????????"),
        GitHubProject("Lumibot", "Lumiwealth/lumibot", "broker abstraction", "?????????", "?????????????"),
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
        message = "??????????" if not errors else "?????????????????"
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
