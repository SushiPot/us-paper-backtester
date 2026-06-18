from __future__ import annotations

from src.agents.base import Agent, AgentContext, AgentResult
from src.config import EmailConfig
from src.notifier import EmailNotifier, build_manager_email_body


class NotificationAgent(Agent):
    """把 Manager 运行结果发送到邮箱。未启用时只记录跳过。"""

    name = "NotificationAgent"

    def _run(self, context: AgentContext) -> AgentResult:
        email_config = EmailConfig(output_dir=context.output_dir)
        notifier = EmailNotifier(email_config)
        body = build_manager_email_body(context.output_dir)
        result = notifier.send("US Paper Backtester Manager Report", body)
        details = {
            "channel": result.channel,
            "recipient": result.recipient,
            "subject": result.subject,
            "notification_status": result.status,
            "error": result.error,
        }
        if result.status == "SENT":
            return AgentResult(self.name, "OK", "邮件通知已发送", details)
        if result.status == "SKIPPED":
            return AgentResult(self.name, "OK", "邮件通知未启用，已跳过", details)
        return AgentResult(self.name, "WARN", f"邮件通知失败: {result.error}", details)
