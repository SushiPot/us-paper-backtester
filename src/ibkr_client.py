from __future__ import annotations

import time
from dataclasses import dataclass
import traceback

from .config import PaperTradingConfig

try:
    from ib_insync import IB, Stock
except ImportError as exc:  # pragma: no cover - ?????????????
    raise ImportError("???? pip install -r requirements.txt ?? ib_insync") from exc


class PaperAccountSafetyError(RuntimeError):
    """?????????"""


@dataclass(frozen=True)
class AccountSnapshot:
    """???????"""

    account: str
    net_liquidation: float
    cash: float
    available_funds: float


@dataclass(frozen=True)
class PositionSnapshot:
    """IBKR ???????"""

    symbol: str
    quantity: int
    avg_cost: float
    market_value: float


class IBKRClient:
    """IBKR ???????? Paper Account ???????"""

    def __init__(self, config: PaperTradingConfig) -> None:
        self.config = config
        self.ib = IB()
        self.account: str | None = None

    def connect(self, require_paper: bool = True) -> None:
        """?? TWS ? IB Gateway?dry_run ???? readonly ???????"""
        if self.config.allow_live_trading:
            raise PaperAccountSafetyError("ALLOW_LIVE_TRADING=True ?????????? IBKR Paper Trading")

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
                f"[ERROR] IBKR ????: host={self.config.ibkr_host}, "
                f"port={self.config.ibkr_port}, clientId={self.config.ibkr_client_id}, "
                f"error={type(exc).__name__}: {exc}",
                flush=True,
            )
            traceback.print_exc()
            raise
        self.ib.reqMarketDataType(self.config.market_data_type)
        accounts = self.ib.managedAccounts()
        if not accounts:
            raise PaperAccountSafetyError("IBKR ????????????")

        self.account = accounts[0]
        if require_paper:
            self.assert_paper_account()

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()

    def assert_paper_account(self) -> None:
        """????????? DU ?????????"""
        if not self.account:
            raise PaperAccountSafetyError("????????????")

        if not self.account.upper().startswith(self.config.paper_account_prefix):
            raise PaperAccountSafetyError(
                f"????? {self.account} ?? Paper Account??????????????"
            )

    def get_account_snapshot(self, require_paper: bool = True) -> AccountSnapshot:
        if require_paper:
            self.assert_paper_account()
        elif not self.account:
            raise PaperAccountSafetyError("????????????")

        values = self.ib.accountSummary(account=self.account)
        parsed: dict[str, float] = {}
        for value in values:
            if value.currency not in ("", "USD"):
                continue
            try:
                parsed[value.tag] = float(value.value)
            except ValueError as exc:
                print(
                    f"[WARN] ????????: tag={value.tag}, value={value.value}, "
                    f"error={type(exc).__name__}: {exc}",
                    flush=True,
                )
                continue

        net_liq = parsed.get("NetLiquidation", 0.0)
        cash = parsed.get("TotalCashValue", parsed.get("CashBalance", 0.0))
        available = parsed.get("AvailableFunds", cash)
        if net_liq <= 0:
            raise PaperAccountSafetyError("????????????? 0?????")

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
            raise PaperAccountSafetyError("????????????")

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
        """????? STK ???????????????"""
        contract = Stock(symbol, "SMART", "USD")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"{symbol} ??????")
        contract = qualified[0]
        if contract.secType != "STK":
            raise PaperAccountSafetyError(f"{symbol} ???????????")
        return contract

    def get_market_price(self, symbol: str) -> float:
        """????????????????????????"""
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
            raise RuntimeError(f"{symbol} ??????/????")
        finally:
            self.ib.cancelMktData(contract)
