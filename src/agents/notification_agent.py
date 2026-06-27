from __future__ import annotations

import pandas as pd

from src.agents.base import Agent, AgentContext, AgentResult
from src.config import EmailConfig
from src.notifier import EmailNotifier, NotificationResult, build_manager_email_body


class NotificationAgent(Agent):
    """? Manager ????????????????????"""

    name = "NotificationAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        email_config = EmailConfig(output_dir=context.output_dir)
        notifier = EmailNotifier(email_config)
        trigger = self._notification_trigger(context)
        body = build_manager_email_body(context.output_dir)
        details = {
            "channel": "email",
            "recipient": email_config.email_to,
            "subject": "US Paper Backtester Manager Report",
            "notification_status": "PENDING",
            "trigger_reason": trigger["reason"],
            "new_trade_count": trigger["new_trade_count"],
            "total_return": trigger["total_return"],
            "profit_loss_state": trigger["profit_loss_state"],
            "error": "",
        }

        if not trigger["should_send"]:
            result = NotificationResult(
                channel="email",
                status="SKIPPED",
                subject="US Paper Backtester Manager Report",
                recipient=email_config.email_to,
                message="No new trade and account PnL is flat; email was not sent.",
            )
            notifier.record_result(result)
            details["notification_status"] = result.status
            return AgentResult(self.name, "OK", "?????????????????", details)

        result = notifier.send("US Paper Backtester Manager Report", body)
        details = {
            "channel": result.channel,
            "recipient": result.recipient,
            "subject": result.subject,
            "notification_status": result.status,
            "trigger_reason": trigger["reason"],
            "new_trade_count": trigger["new_trade_count"],
            "total_return": trigger["total_return"],
            "profit_loss_state": trigger["profit_loss_state"],
            "error": result.error,
        }
        if result.status == "SENT":
            return AgentResult(self.name, "OK", f"???????: {trigger['reason']}", details)
        if result.status == "SKIPPED":
            return AgentResult(self.name, "OK", f"?????????????: {trigger['reason']}", details)
        return AgentResult(self.name, "WARN", f"??????: {result.error}", details)

    def _notification_trigger(self, context: AgentContext) -> dict[str, object]:
        started_at = pd.Timestamp(context.artifacts.get("manager_started_at", pd.Timestamp.min))
        new_trade_count = self._new_trade_count(context, started_at)
        total_return = self._latest_total_return(context)

        reasons = []
        if new_trade_count > 0:
            reasons.append(f"new_trade_count={new_trade_count}")
        if total_return < 0:
            reasons.append(f"account_loss={total_return:.2%}")
            profit_loss_state = "LOSS"
        elif total_return > 0:
            reasons.append(f"account_profit={total_return:.2%}")
            profit_loss_state = "PROFIT"
        else:
            profit_loss_state = "FLAT"

        return {
            "should_send": bool(reasons),
            "reason": "; ".join(reasons) if reasons else "no trade and flat PnL",
            "new_trade_count": new_trade_count,
            "total_return": total_return,
            "profit_loss_state": profit_loss_state,
        }

    def _new_trade_count(self, context: AgentContext, started_at: pd.Timestamp) -> int:
        path = context.output_dir / context.local_config.paper_trade_log_file
        if not path.exists() or path.stat().st_size == 0:
            return 0
        try:
            trades = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return 0
        if trades.empty or "time" not in trades.columns:
            return 0
        trade_times = pd.to_datetime(trades["time"], errors="coerce")
        return int((trade_times >= started_at).sum())

    def _latest_total_return(self, context: AgentContext) -> float:
        path = context.output_dir / context.local_config.local_report_file
        if not path.exists() or path.stat().st_size == 0:
            return 0.0
        try:
            report = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return 0.0
        if report.empty or "total_return" not in report.columns:
            return 0.0
        return float(pd.to_numeric(report["total_return"], errors="coerce").fillna(0.0).iloc[-1])
