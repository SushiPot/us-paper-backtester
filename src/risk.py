from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RiskEvent:
    """???????"""

    event_time: pd.Timestamp
    reason: str
    equity: float


class RiskManager:
    """??????????????????????????"""

    def __init__(self, daily_loss_limit_pct: float, max_drawdown_pct: float) -> None:
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.peak_equity = 0.0
        self.trading_stopped = False
        self.daily_trading_paused = False
        self.current_date: pd.Timestamp | None = None
        self.stop_reason = ""
        self.events: list[RiskEvent] = []

    def update(self, date: pd.Timestamp, equity: float, previous_equity: float | None) -> None:
        self._reset_daily_state(date)
        if self.trading_stopped:
            return

        if self.peak_equity <= 0:
            self.peak_equity = equity
        self.peak_equity = max(self.peak_equity, equity)

        drawdown = equity / self.peak_equity - 1
        if drawdown <= self.max_drawdown_pct:
            self._stop(date, equity, f"??????????: {drawdown:.2%}")
            return

        if previous_equity and previous_equity > 0:
            daily_return = equity / previous_equity - 1
            if daily_return <= self.daily_loss_limit_pct:
                self._pause_for_day(date, equity, f"??????????: {daily_return:.2%}")
                return

    @property
    def can_open_new_positions(self) -> bool:
        """?????????????????????"""
        return not self.trading_stopped and not self.daily_trading_paused

    def _reset_daily_state(self, date: pd.Timestamp) -> None:
        normalized = pd.Timestamp(date).normalize()
        if self.current_date != normalized:
            self.current_date = normalized
            self.daily_trading_paused = False

    def _pause_for_day(self, date: pd.Timestamp, equity: float, reason: str) -> None:
        self.daily_trading_paused = True
        self.events.append(RiskEvent(event_time=date, reason=reason, equity=equity))

    def _stop(self, date: pd.Timestamp, equity: float, reason: str) -> None:
        self.trading_stopped = True
        self.stop_reason = reason
        self.events.append(RiskEvent(event_time=date, reason=reason, equity=equity))
