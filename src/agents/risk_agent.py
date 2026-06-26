from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentResult, read_csv


class RiskAgent(Agent):
    """独立审查当前模拟账户和研究输出的风险。"""

    name = "RiskAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        report = read_csv(context.output_dir / context.local_config.local_report_file)
        positions = read_csv(context.output_dir / context.local_config.positions_file)
        allocation = read_csv(context.output_dir / "portfolio_allocation.csv")
        health = read_csv(context.output_dir / "strategy_health.csv")
        scorecard = read_csv(context.output_dir / "strategy_scorecard.csv")
        data_health = read_csv(context.output_dir / "data_health_summary.csv")
        market_environment = read_csv(context.output_dir / "market_environment_summary.csv")
        macro_environment = read_csv(context.output_dir / "macro_environment_summary.csv")
        warnings = []
        details = {
            "open_positions": int(len(positions)) if not positions.empty else 0,
            "allocation_symbols": int(len(allocation)) if not allocation.empty else 0,
            "strategy_scorecard_rows": int(len(scorecard)) if not scorecard.empty else 0,
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
            overweight_symbols = []
            for _, row in allocation.iterrows():
                symbol = str(row.get("symbol", ""))
                if symbol == "CASH":
                    continue
                max_position_pct = context.local_config.special_max_position_pct.get(
                    symbol,
                    context.local_config.max_position_pct,
                )
                if float(row.get("target_weight", 0.0)) > max_position_pct + 1e-9:
                    overweight_symbols.append(symbol)
            if overweight_symbols:
                warnings.append(f"组合建议存在单标的超限: {', '.join(overweight_symbols)}")

        if not health.empty:
            health_row = health.iloc[-1]
            health_status = str(health_row.get("health_status", ""))
            recommended_action = str(health_row.get("recommended_action", ""))
            overall_score = float(health_row.get("overall_score", 0.0))
            details.update(
                {
                    "strategy_health_score": overall_score,
                    "strategy_health_status": health_status,
                    "strategy_recommended_action": recommended_action,
                }
            )
            if recommended_action in {"OBSERVE_ONLY", "PAUSE_NEW_BUYS"}:
                warnings.append(f"策略健康度建议保守运行: {recommended_action}")

        if not scorecard.empty:
            leader = scorecard.iloc[0]
            details.update(
                {
                    "strategy_leader": str(leader.get("strategy_name", "")),
                    "strategy_leader_score": float(leader.get("strategy_score", 0.0)),
                    "strategy_leader_status": str(leader.get("status", "")),
                }
            )
            weak = scorecard[scorecard["status"].astype(str).isin(["WEAK", "NEEDS_MORE_LIVE_DATA"])]
            if not weak.empty:
                names = ", ".join(weak["strategy_name"].astype(str).head(3).tolist())
                warnings.append(f"策略级样本或表现仍需观察: {names}")

        if not data_health.empty:
            row = data_health.iloc[-1]
            status_text = str(row.get("status", ""))
            details["data_health_status"] = status_text
            details["data_max_lag_calendar_days"] = int(float(row.get("max_lag_calendar_days", 0)))
            if status_text in {"ERROR", "STALE", "WARN"}:
                warnings.append(f"行情数据健康状态需要检查: {status_text}")

        if not market_environment.empty:
            row = market_environment.iloc[-1]
            market_status = str(row.get("market_status", ""))
            recommended_action = str(row.get("recommended_action", ""))
            details["market_environment_status"] = market_status
            details["market_environment_action"] = recommended_action
            if recommended_action in {"PAUSE_NEW_BUYS", "REDUCE_NEW_BUY_SIZE", "OBSERVE_ONLY"}:
                warnings.append(f"市场环境建议保守运行: {market_status}/{recommended_action}")

        if not macro_environment.empty:
            row = macro_environment.iloc[-1]
            macro_status = str(row.get("macro_status", ""))
            recommended_action = str(row.get("recommended_action", ""))
            details["macro_environment_status"] = macro_status
            details["macro_environment_action"] = recommended_action
            details["macro_risk_score"] = float(row.get("risk_score", 0.0))
            if recommended_action in {"PAUSE_NEW_BUYS", "REDUCE_NEW_BUY_SIZE", "OBSERVE_ONLY"}:
                warnings.append(f"宏观环境建议保守运行: {macro_status}/{recommended_action}")

        status = "WARN" if warnings else "OK"
        message = "；".join(warnings) if warnings else "当前未发现硬性风控违规"
        details["warnings"] = warnings
        context.artifacts["risk"] = details
        return AgentResult(self.name, status, message, details)
