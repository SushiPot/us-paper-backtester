from __future__ import annotations

from dataclasses import dataclass

from pandas import Timestamp


@dataclass
class Position:
    """单个持仓。"""

    symbol: str
    shares: int
    entry_price: float
    entry_date: Timestamp

    def market_value(self, price: float) -> float:
        return self.shares * price

    def return_pct(self, price: float) -> float:
        return price / self.entry_price - 1


@dataclass
class Trade:
    """完整的一笔买卖交易。"""

    trade_time: Timestamp
    symbol: str
    buy_price: float
    sell_price: float
    shares: int
    return_pct: float
    account_balance: float
    reason: str


class Portfolio:
    """现金和持仓管理，严格禁止杠杆和做空。"""

    def __init__(self, initial_cash: float) -> None:
        self.cash = initial_cash
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []

    def total_equity(self, prices: dict[str, float]) -> float:
        equity = self.cash
        for symbol, position in self.positions.items():
            if symbol in prices:
                equity += position.market_value(prices[symbol])
        return equity

    def buy(self, symbol: str, date: Timestamp, price: float, max_amount: float) -> bool:
        """按最大投入金额买入整数股，不允许现金为负。"""
        spend = min(max_amount, self.cash)
        shares = int(spend // price)
        if shares <= 0:
            return False

        cost = shares * price
        if cost > self.cash:
            return False

        self.cash -= cost
        self.positions[symbol] = Position(symbol=symbol, shares=shares, entry_price=price, entry_date=date)
        return True

    def sell(self, symbol: str, date: Timestamp, price: float, account_balance: float, reason: str) -> Trade:
        position = self.positions.pop(symbol)
        proceeds = position.shares * price
        self.cash += proceeds

        trade = Trade(
            trade_time=date,
            symbol=symbol,
            buy_price=position.entry_price,
            sell_price=price,
            shares=position.shares,
            return_pct=position.return_pct(price),
            account_balance=account_balance,
            reason=reason,
        )
        self.trades.append(trade)
        return trade
