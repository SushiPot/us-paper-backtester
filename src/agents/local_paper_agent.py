from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentResult, read_csv
from src.local_paper_trader import LocalPaperTrader


class LocalPaperAgent(Agent):
    """运行一次本地模拟盘，只使用虚拟资金。"""

    name = "LocalPaperAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        LocalPaperTrader(context.local_config).run_once()
        account = read_csv(context.output_dir / context.local_config.virtual_account_file)
        report = read_csv(context.output_dir / context.local_config.local_report_file)

        details = {}
        if not account.empty:
            row = account.iloc[-1]
            details["market_date"] = str(row.get("as_of_date", ""))
            details["equity"] = float(row.get("equity", 0.0))
            details["virtual_cash"] = float(row.get("virtual_cash", 0.0))
        if not report.empty:
            row = report.iloc[-1]
            details["total_return"] = float(row.get("total_return", 0.0))
            details["max_drawdown"] = float(row.get("max_drawdown", 0.0))
            details["sharpe_ratio"] = float(row.get("sharpe_ratio", 0.0))

        context.artifacts["local_paper"] = details
        return AgentResult(self.name, "OK", "本地模拟盘已完成一次运行", details)
