from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from .config import EmailConfig
from .database import get_store


@dataclass(frozen=True)
class NotificationResult:
    """一次通知发送结果。"""

    channel: str
    status: str
    subject: str
    recipient: str
    message: str
    error: str = ""


class EmailNotifier:
    """SMTP 邮件通知器。默认安全关闭，密码只从环境变量读取。"""

    def __init__(self, config: EmailConfig | None = None) -> None:
        self.config = config or EmailConfig()
        self.output_dir = self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def send(self, subject: str, body: str, force: bool = False) -> NotificationResult:
        if not self.config.enabled and not force:
            result = NotificationResult(
                channel="email",
                status="SKIPPED",
                subject=subject,
                recipient=self.config.email_to,
                message="EMAIL_ENABLED is false; email was not sent.",
            )
            self._record(result)
            return result

        missing = self._missing_fields()
        if missing:
            result = NotificationResult(
                channel="email",
                status="ERROR",
                subject=subject,
                recipient=self.config.email_to,
                message="Email configuration is incomplete.",
                error="Missing: " + ", ".join(missing),
            )
            self._record(result)
            return result

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.config.email_from
        message["To"] = self.config.email_to
        message.set_content(body)

        try:
            if self.config.use_tls:
                with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                    smtp.login(self.config.smtp_username, self.config.smtp_password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
                    smtp.login(self.config.smtp_username, self.config.smtp_password)
                    smtp.send_message(message)

            result = NotificationResult(
                channel="email",
                status="SENT",
                subject=subject,
                recipient=self.config.email_to,
                message="Email sent successfully.",
            )
        except Exception as exc:
            result = NotificationResult(
                channel="email",
                status="ERROR",
                subject=subject,
                recipient=self.config.email_to,
                message="Email send failed.",
                error=f"{type(exc).__name__}: {exc}",
            )

        self._record(result)
        return result

    def _missing_fields(self) -> list[str]:
        fields = {
            "SMTP_HOST": self.config.smtp_host,
            "SMTP_USERNAME": self.config.smtp_username,
            "SMTP_PASSWORD": self.config.smtp_password,
            "EMAIL_FROM": self.config.email_from,
            "EMAIL_TO": self.config.email_to,
        }
        return [name for name, value in fields.items() if not str(value).strip()]

    def _record(self, result: NotificationResult) -> None:
        row = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "channel": result.channel,
                    "status": result.status,
                    "subject": result.subject,
                    "recipient": result.recipient,
                    "message": result.message,
                    "error": result.error,
                }
            ]
        )
        path = self.output_dir / self.config.notification_log_file
        row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
        get_store().append_frame("notifications", row)


def build_manager_email_body(output_dir: Path = Path("outputs")) -> str:
    """生成一封简短的 Manager 状态邮件正文。"""
    manager_report = output_dir / "manager_report.md"
    local_report = _read_csv(output_dir / "local_paper_report.csv")
    scorecard = _read_csv(output_dir / "strategy_scorecard.csv")
    lines = [
        "US Paper Backtester notification",
        "",
        f"Generated at: {pd.Timestamp.now()}",
        "",
    ]
    if not local_report.empty:
        row = local_report.iloc[-1]
        lines.extend(
            [
                f"Equity: {float(row.get('equity', 0.0)):.2f}",
                f"Virtual cash: {float(row.get('virtual_cash', 0.0)):.2f}",
                f"Total return: {float(row.get('total_return', 0.0)):.2%}",
                f"Open positions: {int(float(row.get('open_positions', 0)))}",
                "",
            ]
        )
    if not scorecard.empty:
        row = scorecard.iloc[0]
        lines.extend(
            [
                f"Strategy leader: {row.get('strategy_name', '')}",
                f"Strategy score: {float(row.get('strategy_score', 0.0)):.2f}",
                f"Strategy status: {row.get('status', '')}",
                "",
            ]
        )
    if manager_report.exists():
        text = manager_report.read_text(encoding="utf-8", errors="replace")
        lines.extend(["Manager report excerpt:", "", text[:3000]])
    return "\n".join(lines)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
