from __future__ import annotations

import time
from dataclasses import dataclass
import traceback

from .config import PaperTradingConfig

try:
    from ib_insync import IB, Stock
except ImportError as exc:  # pragma: no cover - 给未安装依赖时更清楚的提示
    raise ImportError("请先运行 pip install -r requirements.txt 安装 ib_insync") from exc


class PaperAccountSafetyError(RuntimeError):
    """账户安全检查失败。"""


@dataclass(frozen=True)
class AccountSnapshot:
    """账户资金快照。"""

    account: str
    net_liquidation: float
    cash: float
    available_funds: float


@dataclass(frozen=True)
class PositionSnapshot:
    """IBKR 当前持仓快照。"""

    symbol: str
    quantity: int
    avg_cost: float
    market_value: float


class IBKRClient:
    """IBKR 连接封装，只允许 Paper Account 通过安全检查。"""

    def __init__(self, config: PaperTradingConfig) -> None:
        self.config = config
        self.ib = IB()
        self.account: str | None = None

    def connect(self, require_paper: bool = True) -> None:
        """连接 TWS 或 IB Gateway。dry_run 模式使用 readonly 作为额外保险。"""
        if self.config.allow_live_trading:
            raise PaperAccountSafetyError("ALLOW_LIVE_TRADING=True 被拒绝：本系统只允许 IBKR Paper Trading")

        try:
            self.ib.connect(
                self.config.ibkr_host,
                self.config.ibkr_port,
                clientId=self.config.ibkr_client_id,
                timeout=self.config.ibkr_connect_timeout_seconds,
                readonly=self.config.dry_run,
            )
        except Exception as exc:
            print(
                f"[ERROR] IBKR 连接失败: host={self.config.ibkr_host}, "
                f"port={self.config.ibkr_port}, clientId={self.config.ibkr_client_id}, "
                f"error={type(exc).__name__}: {exc}",
                flush=True,
            )
            traceback.print_exc()
            raise
        self.ib.reqMarketDataType(self.config.market_data_type)
        accounts = self.ib.managedAccounts()
        if not accounts:
            raise PaperAccountSafetyError("IBKR 没有返回任何账户，已停止")

        self.account = accounts[0]
        if require_paper:
            self.assert_paper_account()

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    def assert_paper_account(self) -> None:
        """下单前必须调用。非 DU 开头账户立即停止。"""
        if not self.account:
            raise PaperAccountSafetyError("尚未读取到账户，禁止交易")

        if not self.account.upper().startswith(self.config.paper_account_prefix):
            raise PaperAccountSafetyError(
                f"检测到账户 {self.account} 不是 Paper Account，本系统禁止连接真实资金账户"
            )

    def get_account_snapshot(self, require_paper: bool = True) -> AccountSnapshot:
        if require_paper:
            self.assert_paper_account()
        elif not self.account:
            raise PaperAccountSafetyError("尚未读取到账户，禁止交易")

        values = self.ib.accountSummary(account=self.account)
        parsed: dict[str, float] = {}
        for value in values:
            if value.currency not in ("", "USD"):
                continue
            try:
                parsed[value.tag] = float(value.value)
            except ValueError as exc:
                print(
                    f"[WARN] 账户字段解析失败: tag={value.tag}, value={value.value}, "
                    f"error={type(exc).__name__}: {exc}",
                    flush=True,
                )
                continue

        net_liq = parsed.get("NetLiquidation", 0.0)
        cash = parsed.get("TotalCashValue", parsed.get("CashBalance", 0.0))
        available = parsed.get("AvailableFunds", cash)
        if net_liq <= 0:
            raise PaperAccountSafetyError("账户权益读取失败或小于等于 0，禁止交易")

        return AccountSnapshot(
            account=self.account,
            net_liquidation=net_liq,
            cash=max(cash, 0.0),
            available_funds=max(min(available, cash if cash > 0 else available), 0.0),
        )

    def get_positions(self, require_paper: bool = True) -> dict[str, PositionSnapshot]:
        if require_paper:
            self.assert_paper_account()
        elif not self.account:
            raise PaperAccountSafetyError("尚未读取到账户，禁止交易")

        positions: dict[str, PositionSnapshot] = {}
        for position in self.ib.positions():
            if position.account != self.account:
                continue
            contract = position.contract
            if contract.secType != "STK":
                continue
            quantity = int(position.position)
            if quantity <= 0:
                continue
            market_value = quantity * float(position.avgCost)
            positions[contract.symbol] = PositionSnapshot(
                symbol=contract.symbol,
                quantity=quantity,
                avg_cost=float(position.avgCost),
                market_value=market_value,
            )
        return positions

    def get_stock_contract(self, symbol: str):
        """只创建美股 STK 合约，禁止期权等其他资产类型。"""
        contract = Stock(symbol, "SMART", "USD")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"{symbol} 合约确认失败")
        contract = qualified[0]
        if contract.secType != "STK":
            raise PaperAccountSafetyError(f"{symbol} 不是股票合约，禁止交易")
        return contract

    def get_market_price(self, symbol: str) -> float:
        """读取实时或延迟行情，失败时抛出异常，不静默下单。"""
        contract = self.get_stock_contract(symbol)
        ticker = self.ib.reqMktData(contract, "", False, False)
        try:
            for _ in range(10):
                self.ib.sleep(0.5)
                price = ticker.marketPrice()
                if price and price > 0:
                    return float(price)
                for candidate in (ticker.last, ticker.close, ticker.bid, ticker.ask):
                    if candidate and candidate > 0:
                        return float(candidate)
                time.sleep(0.1)
            raise RuntimeError(f"{symbol} 没有可用实时/延迟行情")
        finally:
            self.ib.cancelMktData(contract)
