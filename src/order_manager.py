from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import PaperTradingConfig
from .ibkr_client import AccountSnapshot, IBKRClient, PaperAccountSafetyError, PositionSnapshot
from .live_risk import LiveRiskManager, PositionStateStore

try:
    from ib_insync import MarketOrder
except ImportError as exc:  # pragma: no cover
    raise ImportError("???? pip install -r requirements.txt ?? ib_insync") from exc


@dataclass(frozen=True)
class OrderIntent:
    """??????????"""

    symbol: str
    action: str
    quantity: int
    estimated_price: float
    reason: str


@dataclass(frozen=True)
class OrderSubmitResult:
    """??????????????????"""

    risk_passed: bool
    sent_to_paper: bool
    status: str
    reject_reason: str


class OrderManager:
    """??????????? IBKR ???????????"""

    def __init__(self, config: PaperTradingConfig, client: IBKRClient, risk: LiveRiskManager) -> None:
        self.config = config
        self.client = client
        self.risk = risk
        self.output_dir = config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.position_state = PositionStateStore(config.output_dir, config.paper_position_state_file)

    def submit(
        self,
        intent: OrderIntent,
        account: AccountSnapshot,
        positions: dict[str, PositionSnapshot],
    ) -> OrderSubmitResult:
        self.client.assert_paper_account()
        action = intent.action.upper()
        if action not in ("BUY", "SELL"):
            raise PaperAccountSafetyError("????? BUY/SELL ??")

        decision = self.risk.validate_order(
            action=action,
            symbol=intent.symbol,
            quantity=intent.quantity,
            estimated_price=intent.estimated_price,
            account=account,
            positions=positions,
        )
        self._print_pre_order(intent, account, decision.reason)

        if not decision.allowed:
            self._append_order_log(intent, "REJECTED_BY_RISK", decision.reason)
            return OrderSubmitResult(False, False, "REJECTED_BY_RISK", decision.reason)

        if self.config.dry_run:
            self._append_order_log(intent, "DRY_RUN", "dry_run=True????????????")
            return OrderSubmitResult(True, False, "DRY_RUN", "")

        # ????????????????? Paper Account?????????????? DAY ??
        self.client.assert_paper_account()
        contract = self.client.get_stock_contract(intent.symbol)
        order = MarketOrder(action, intent.quantity, tif="DAY", outsideRth=False)
        trade = self.client.ib.placeOrder(contract, order)
        self.client.ib.sleep(1)

        status = getattr(trade.orderStatus, "status", "SUBMITTED")
        self._append_order_log(intent, status, "???? IBKR Paper Trading")
        self._append_fills(trade)
        return OrderSubmitResult(True, True, status, "")

    def _print_pre_order(self, intent: OrderIntent, account: AccountSnapshot, risk_status: str) -> None:
        amount = intent.quantity * intent.estimated_price
        print("????????")
        print(f"????: {intent.symbol}")
        print(f"??/????: {intent.action.upper()}")
        print(f"??: {intent.quantity}")
        print(f"????: {intent.estimated_price:.2f}")
        print(f"????: {amount:.2f}")
        print(f"??????: {account.net_liquidation:.2f}")
        print(f"??????: {risk_status}")

    def _append_order_log(self, intent: OrderIntent, status: str, message: str) -> None:
        path = self.output_dir / self.config.paper_order_log_file
        row = pd.DataFrame(
            [
                {
                    "??": pd.Timestamp.now(),
                    "????": intent.symbol,
                    "??": intent.action.upper(),
                    "??": intent.quantity,
                    "????": intent.estimated_price,
                    "????": intent.quantity * intent.estimated_price,
                    "????": status,
                    "??": intent.reason,
                    "??": message,
                }
            ]
        )
        _append_csv(path, row)

    def _append_fills(self, trade) -> None:
        if not trade.fills:
            return
        rows = []
        for fill in trade.fills:
            execution = fill.execution
            rows.append(
                {
                    "??": pd.Timestamp.now(),
                    "????": fill.contract.symbol,
                    "??": execution.side,
                    "??": execution.shares,
                    "????": execution.price,
                    "????": execution.shares * execution.price,
                    "????": execution.orderId,
                    "????": execution.execId,
                }
            )
        _append_csv(self.output_dir / self.config.paper_trade_log_file, pd.DataFrame(rows))
        self._update_position_state_from_fills(trade)

    def _update_position_state_from_fills(self, trade) -> None:
        for fill in trade.fills:
            symbol = fill.contract.symbol
            side = str(fill.execution.side).upper()
            shares = int(fill.execution.shares)
            price = float(fill.execution.price)
            if side in ("BOT", "BUY"):
                self.position_state.update_buy(symbol, shares, price)
            elif side in ("SLD", "SELL"):
                self.position_state.remove(symbol)


def _append_csv(path: Path, row: pd.DataFrame) -> None:
    row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
