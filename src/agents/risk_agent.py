from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentResult, read_csv


class RiskAgent(Agent):
    """独立审查当前模拟账户和研究输出的风险。"""

    name = "RiskAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        report = read_csv(context.output_dir / context.local_config.local_report_file)
        positions = read_csv(context.output_dir / context.local_config.positions_file)
        allocation = read_csv(context.output_dir / "portfolio_allocation.csv")
        warnings = []
        details = {
            "open_positions": int(len(positions)) if not positions.empty else 0,
            "allocation_symbols": int(len(allocation)) if not allocation.empty else 0,
        }

        if report.empty:
            warnings.append("缺少本地模拟盘报告")
        else:
            row = report.iloc[-1]
            total_return = float(row.get("total_return", 0.0))
            max_drawdown = float(row.get("max_drawdown", 0.0))
            sharpe_ratio = float(row.get("sharpe_ratio", 0.0))
            details.update(
                {
                    "total_return": total_return,
                    "max_drawdown": max_drawdown,
                    "sharpe_ratio": sharpe_ratio,
                    "gross_exposure": float(row.get("gross_exposure", 0.0)),
                    "cash_pct": float(row.get("cash_pct", 0.0)),
                }
            )
            if max_drawdown <= context.local_config.max_account_drawdown_pct:
                warnings.append("账户最大回撤触及停止阈值")
            if sharpe_ratio < 0:
                warnings.append("夏普比率为负，策略近期风险收益不佳")
            if total_return < 0:
                warnings.append("总收益率为负，继续观察策略稳定性")

        if not allocation.empty and "target_weight" in allocation.columns:
            overweight = allocation[
                (allocation["symbol"] != "CASH")
                & (allocation["target_weight"].astype(float) > context.local_config.max_position_pct + 1e-9)
            ]
            if not overweight.empty:
                warnings.append("组合建议存在单标的超限")

        status = "WARN" if warnings else "OK"
        message = "；".join(warnings) if warnings else "当前未发现硬性风控违规"
        details["warnings"] = warnings
        context.artifacts["risk"] = details
        return AgentResult(self.name, status, message, details)
