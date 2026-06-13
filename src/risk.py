from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RiskEvent:
    """风控事件记录。"""

    event_time: pd.Timestamp
    reason: str
    equity: float


class RiskManager:
    """账户级风控：每日亏损和最大回撤。"""

    def __init__(self, daily_loss_limit_pct: float, max_drawdown_pct: float) -> None:
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.peak_equity = 0.0
        self.trading_stopped = False
        self.stop_reason = ""
        self.events: list[RiskEvent] = []

    def update(self, date: pd.Timestamp, equity: float, previous_equity: float | None) -> None:
        if self.trading_stopped:
            return

        if self.peak_equity <= 0:
            self.peak_equity = equity
        self.peak_equity = max(self.peak_equity, equity)

        if previous_equity and previous_equity > 0:
            daily_return = equity / previous_equity - 1
            if daily_return <= self.daily_loss_limit_pct:
                self._stop(date, equity, f"触发每日最大亏损限制: {daily_return:.2%}")
                return

        drawdown = equity / self.peak_equity - 1
        if drawdown <= self.max_drawdown_pct:
            self._stop(date, equity, f"触发账户最大回撤限制: {drawdown:.2%}")

    def _stop(self, date: pd.Timestamp, equity: float, reason: str) -> None:
        self.trading_stopped = True
        self.stop_reason = reason
        self.events.append(RiskEvent(event_time=date, reason=reason, equity=equity))
