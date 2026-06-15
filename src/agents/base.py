from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

import pandas as pd

from src.config import BacktestConfig, LocalPaperConfig


@dataclass
class AgentContext:
    """所有 Agent 共享的运行上下文。"""

    local_config: LocalPaperConfig = field(default_factory=LocalPaperConfig)
    backtest_config: BacktestConfig = field(default_factory=BacktestConfig)
    output_dir: Path = Path("outputs")
    artifacts: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    """单个 Agent 的执行结果。"""

    agent: str
    status: str
    message: str
    details: dict[str, object] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


class Agent:
    """本地规则型 Agent 基类。"""

    name = "Agent"

    def run(self, context: AgentContext) -> AgentResult:
        start = perf_counter()
        try:
            result = self._run(context)
            return AgentResult(
                agent=self.name,
                status=result.status,
                message=result.message,
                details=result.details,
                elapsed_seconds=perf_counter() - start,
            )
        except Exception as exc:
            return AgentResult(
                agent=self.name,
                status="ERROR",
                message=f"{type(exc).__name__}: {exc}",
                details={},
                elapsed_seconds=perf_counter() - start,
            )

    def _run(self, context: AgentContext) -> AgentResult:
        raise NotImplementedError


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def append_agent_log(output_dir: Path, results: list[AgentResult]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "time": pd.Timestamp.now(),
            "agent": result.agent,
            "status": result.status,
            "message": result.message,
            "elapsed_seconds": result.elapsed_seconds,
            "details": result.details,
        }
        for result in results
    ]
    frame = pd.DataFrame(rows)
    path = output_dir / "agent_run_log.csv"
    frame.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
