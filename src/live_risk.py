from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .config import PaperTradingConfig
from .ibkr_client import AccountSnapshot, PositionSnapshot
from .market_calendar import is_regular_us_market_hours


@dataclass(frozen=True)
class RiskDecision:
    """????????"""

    allowed: bool
    reason: str


class LiveRiskManager:
    """IBKR Paper Trading ???????"""

    def __init__(self, config: PaperTradingConfig) -> None:
        self.config = config
        self.daily_start_equity: float | None = None
        self.peak_equity: float | None = None
        self.stopped = False
        self.stop_reason = ""

    def update_account_risk(self, account: AccountSnapshot) -> RiskDecision:
        equity = account.net_liquidation
        if self.daily_start_equity is None:
            self.daily_start_equity = equity
        if self.peak_equity is None:
            self.peak_equity = equity
        self.peak_equity = max(self.peak_equity, equity)

        daily_return = equity / self.daily_start_equity - 1
        drawdown = equity / self.peak_equity - 1

        if daily_return <= self.config.daily_loss_limit_pct:
            return self._stop(f"??????????: {daily_return:.2%}")
        if drawdown <= self.config.max_account_drawdown_pct:
            return self._stop(f"??????????: {drawdown:.2%}")
        return RiskDecision(True, "??????")

    def validate_order(
        self,
        action: str,
        symbol: str,
        quantity: int,
        estimated_price: float,
        account: AccountSnapshot,
        positions: dict[str, PositionSnapshot],
    ) -> RiskDecision:
        if self.stopped:
            return RiskDecision(False, self.stop_reason)
        if self.config.enforce_regular_trading_hours and not is_regular_us_market_hours():
            return RiskDecision(False, "?????????????????????")
        if quantity <= 0:
            return RiskDecision(False, "???????? 0")

        amount = quantity * estimated_price
        action = action.upper()

        if action == "BUY":
            if len(positions) >= self.config.max_positions and symbol not in positions:
                return RiskDecision(False, "??????????")
            if amount > account.net_liquidation * self.config.max_position_pct:
                return RiskDecision(False, "???? 20% ????")
            if amount > account.available_funds:
                return RiskDecision(False, "???????????")
            return RiskDecision(True, "??????")

        if action == "SELL":
            position = positions.get(symbol)
            if not position or position.quantity < quantity:
                return RiskDecision(False, "???????????????")
            return RiskDecision(True, "??????")

        return RiskDecision(False, "??? BUY ? SELL")

    def _stop(self, reason: str) -> RiskDecision:
        self.stopped = True
        self.stop_reason = reason
        return RiskDecision(False, reason)


def append_risk_log(output_dir: Path, filename: str, event_type: str, message: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    row = pd.DataFrame(
        [
            {
                "??": pd.Timestamp.now(),
                "????": event_type,
                "??": message,
            }
        ]
    )
    row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")


class PositionStateStore:
    """????????? Paper ????????? 30 ???????"""

    def __init__(self, output_dir: Path, filename: str) -> None:
        self.path = output_dir / filename
        output_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=["symbol", "entry_date", "quantity", "avg_cost"])
        return pd.read_csv(self.path, parse_dates=["entry_date"])

    def get_entry_date(self, symbol: str) -> pd.Timestamp | None:
        state = self.load()
        rows = state[state["symbol"] == symbol]
        if rows.empty:
            return None
        return pd.Timestamp(rows.iloc[-1]["entry_date"])

    def update_buy(self, symbol: str, quantity: int, price: float) -> None:
        state = self.load()
        state = state[state["symbol"] != symbol]
        state = pd.concat(
            [
                state,
                pd.DataFrame(
                    [
                        {
                            "symbol": symbol,
                            "entry_date": pd.Timestamp.now().normalize(),
                            "quantity": quantity,
                            "avg_cost": price,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        state.to_csv(self.path, index=False, encoding="utf-8-sig")

    def remove(self, symbol: str) -> None:
        state = self.load()
        state = state[state["symbol"] != symbol]
        state.to_csv(self.path, index=False, encoding="utf-8-sig")
