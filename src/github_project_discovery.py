from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import requests

from .database import get_store
from .credentials import get_github_token


@dataclass(frozen=True)
class GitHubSearchQuery:
    """GitHub 项目搜索关键词。"""

    query: str
    category: str
    reason: str


class GitHubProjectDiscovery:
    """联网搜索 GitHub 项目并为本项目的后续集成排序。"""

    QUERIES = [
        GitHubSearchQuery("python trading backtesting framework stars:>500", "backtesting", "提升回测和策略验证能力"),
        GitHubSearchQuery("python portfolio optimization risk parity stars:>300", "portfolio", "提升仓位和风险预算能力"),
        GitHubSearchQuery("python financial sentiment analysis FinBERT stars:>300", "sentiment", "构建新闻/情绪风险过滤器"),
        GitHubSearchQuery("python market calendar trading hours stars:>100", "calendar", "提升交易日和休市判断准确性"),
        GitHubSearchQuery("python algorithmic trading risk management stars:>300", "risk", "提升风控和监控能力"),
        GitHubSearchQuery("python trading reinforcement learning stars:>500", "research_ai", "仅用于研究模式的AI策略实验"),
    ]

    def __init__(self, output_dir: Path = Path("outputs"), per_query: int = 5) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.per_query = per_query

    def run(self) -> pd.DataFrame:
        rows = []
        errors = []
        for query in self.QUERIES:
            try:
                rows.extend(self._search(query))
            except Exception as exc:
                errors.append(f"{query.query}: {type(exc).__name__}: {exc}")

        frame = pd.DataFrame(rows)
        if frame.empty:
            frame = pd.DataFrame(self._fallback_rows())
        else:
            frame = frame.sort_values(["integration_score", "stars"], ascending=[False, False])
            frame = frame.drop_duplicates(subset=["repo"], keep="first")

        frame.to_csv(self.output_dir / "github_project_candidates.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame, errors)
        get_store().append_generic_frame("github_project_candidates", "github_project_candidates.csv", frame)
        if errors:
            error_frame = pd.DataFrame([{"error": error} for error in errors])
            get_store().append_generic_frame("github_project_discovery_errors", "github_project_discovery", error_frame)
        return frame

    def _search(self, query: GitHubSearchQuery) -> list[dict[str, object]]:
        url = "https://api.github.com/search/repositories"
        params = {
            "q": query.query,
            "sort": "stars",
            "order": "desc",
            "per_page": self.per_query,
        }
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "us-paper-backtester-github-discovery",
        }
        token = get_github_token(self.output_dir.parent)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()
        rows = []
        for item in payload.get("items", []):
            stars = int(item.get("stargazers_count", 0))
            forks = int(item.get("forks_count", 0))
            open_issues = int(item.get("open_issues_count", 0))
            updated_at = str(item.get("updated_at", ""))
            score = self._score(stars, forks, open_issues, updated_at, query.category)
            rows.append(
                {
                    "category": query.category,
                    "name": item.get("name", ""),
                    "repo": item.get("full_name", ""),
                    "description": item.get("description", ""),
                    "stars": stars,
                    "forks": forks,
                    "open_issues": open_issues,
                    "updated_at": updated_at,
                    "html_url": item.get("html_url", ""),
                    "search_query": query.query,
                    "reason": query.reason,
                    "integration_score": score,
                    "suggested_action": self._suggest_action(query.category, score),
                }
            )
        return rows

    @staticmethod
    def _score(stars: int, forks: int, open_issues: int, updated_at: str, category: str) -> float:
        score = min(55.0, stars / 120.0) + min(20.0, forks / 120.0)
        if updated_at >= "2025":
            score += 15.0
        if open_issues > 500:
            score -= 8.0
        if category in {"calendar", "portfolio", "risk"}:
            score += 6.0
        if category == "research_ai":
            score -= 5.0
        return round(max(0.0, min(100.0, score)), 2)

    @staticmethod
    def _suggest_action(category: str, score: float) -> str:
        if score < 45:
            return "WATCH_ONLY"
        if category == "research_ai":
            return "RESEARCH_ONLY"
        if category in {"calendar", "risk"}:
            return "SMALL_SAFE_INTEGRATION"
        if category == "portfolio":
            return "OPTIONAL_DEPENDENCY"
        return "REFERENCE_IMPLEMENTATION"

    @staticmethod
    def _fallback_rows() -> list[dict[str, object]]:
        fallback = [
            ("calendar", "rsheftel/pandas_market_calendars", "market calendar", "SMALL_SAFE_INTEGRATION"),
            ("portfolio", "dcajasn/Riskfolio-Lib", "risk parity and CVaR allocation", "OPTIONAL_DEPENDENCY"),
            ("backtesting", "polakowo/vectorbt", "fast vectorized backtesting", "REFERENCE_IMPLEMENTATION"),
            ("sentiment", "ProsusAI/finBERT", "financial sentiment model", "RESEARCH_ONLY"),
        ]
        rows = []
        for category, repo, reason, action in fallback:
            rows.append(
                {
                    "category": category,
                    "name": repo.split("/")[-1],
                    "repo": repo,
                    "description": "Fallback candidate; GitHub API unavailable or rate limited.",
                    "stars": 0,
                    "forks": 0,
                    "open_issues": 0,
                    "updated_at": "",
                    "html_url": f"https://github.com/{quote_plus(repo).replace('%2F', '/')}",
                    "search_query": "fallback",
                    "reason": reason,
                    "integration_score": 30.0,
                    "suggested_action": action,
                }
            )
        return rows

    def _write_report(self, frame: pd.DataFrame, errors: list[str]) -> None:
        lines = [
            "# GitHub Project Discovery",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "## Top Candidates",
            "",
        ]
        if frame.empty:
            lines.append("No candidates found.")
        else:
            columns = ["category", "repo", "stars", "integration_score", "suggested_action", "reason"]
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in frame.head(20).to_dict(orient="records"):
                lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
        if errors:
            lines.extend(["", "## Errors", ""])
            lines.extend(f"- {error}" for error in errors)
        (self.output_dir / "github_project_discovery.md").write_text("\n".join(lines), encoding="utf-8")
