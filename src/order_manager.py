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
    raise ImportError("请先运行 pip install -r requirements.txt 安装 ib_insync") from exc


@dataclass(frozen=True)
class OrderIntent:
    """策略生成的订单意图。"""

    symbol: str
    action: str
    quantity: int
    estimated_price: float
    reason: str


@dataclass(frozen=True)
class OrderSubmitResult:
    """订单提交结果，用于第三阶段决策日志。"""

    risk_passed: bool
    sent_to_paper: bool
    status: str
    reject_reason: str


class OrderManager:
    """订单安全出口。所有发送 IBKR 的订单都必须经过这里。"""

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
            raise PaperAccountSafetyError("只允许股票 BUY/SELL 订单")

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
            self._append_order_log(intent, "DRY_RUN", "dry_run=True，只打印模拟订单，不发送")
            return OrderSubmitResult(True, False, "DRY_RUN", "")

        # 最后一层安全锁：真实发送前再次确认 Paper Account，并强制常规时段、股票、市价 DAY 单。
        self.client.assert_paper_account()
        contract = self.client.get_stock_contract(intent.symbol)
        order = MarketOrder(action, intent.quantity, tif="DAY", outsideRth=False)
        trade = self.client.ib.placeOrder(contract, order)
        self.client.ib.sleep(1)

        status = getattr(trade.orderStatus, "status", "SUBMITTED")
        self._append_order_log(intent, status, "已发送到 IBKR Paper Trading")
        self._append_fills(trade)
        return OrderSubmitResult(True, True, status, "")

    def _print_pre_order(self, intent: OrderIntent, account: AccountSnapshot, risk_status: str) -> None:
        amount = intent.quantity * intent.estimated_price
        print("准备提交模拟订单")
        print(f"股票代码: {intent.symbol}")
        print(f"买入/卖出方向: {intent.action.upper()}")
        print(f"数量: {intent.quantity}")
        print(f"预计价格: {intent.estimated_price:.2f}")
        print(f"预计金额: {amount:.2f}")
        print(f"当前账户余额: {account.net_liquidation:.2f}")
        print(f"当前风险状态: {risk_status}")

    def _append_order_log(self, intent: OrderIntent, status: str, message: str) -> None:
        path = self.output_dir / self.config.paper_order_log_file
        row = pd.DataFrame(
            [
                {
                    "时间": pd.Timestamp.now(),
                    "股票代码": intent.symbol,
                    "方向": intent.action.upper(),
                    "数量": intent.quantity,
                    "预计价格": intent.estimated_price,
                    "预计金额": intent.quantity * intent.estimated_price,
                    "订单状态": status,
                    "原因": intent.reason,
                    "说明": message,
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
                    "时间": pd.Timestamp.now(),
                    "股票代码": fill.contract.symbol,
                    "方向": execution.side,
                    "数量": execution.shares,
                    "成交价格": execution.price,
                    "成交金额": execution.shares * execution.price,
                    "订单编号": execution.orderId,
                    "成交编号": execution.execId,
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
