from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .portfolio import Trade
from .risk import RiskEvent


@dataclass(frozen=True)
class BacktestReport:
    """回测绩效指标。"""

    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    avg_profit_loss_ratio: float
    trade_count: int


class ReportWriter:
    """保存交易日志、绩效报告和资金曲线图。"""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_trade_log(self, trades: list[Trade], filename: str) -> None:
        rows = [
            {
                "交易时间": trade.trade_time,
                "股票代码": trade.symbol,
                "买入价格": trade.buy_price,
                "卖出价格": trade.sell_price,
                "股数": trade.shares,
                "收益率": trade.return_pct,
                "账户余额": trade.account_balance,
                "卖出原因": trade.reason,
            }
            for trade in trades
        ]
        pd.DataFrame(rows).to_csv(self.output_dir / filename, index=False, encoding="utf-8-sig")

    def write_report(self, report: BacktestReport, filename: str) -> None:
        pd.DataFrame(
            [
                {
                    "总收益率": report.total_return,
                    "年化收益率": report.annual_return,
                    "最大回撤": report.max_drawdown,
                    "夏普比率": report.sharpe_ratio,
                    "胜率": report.win_rate,
                    "平均盈亏比": report.avg_profit_loss_ratio,
                    "交易次数": report.trade_count,
                }
            ]
        ).to_csv(self.output_dir / filename, index=False, encoding="utf-8-sig")

    def write_risk_log(self, events: list[RiskEvent], filename: str) -> None:
        rows = [
            {
                "触发时间": event.event_time,
                "原因": event.reason,
                "账户权益": event.equity,
            }
            for event in events
        ]
        pd.DataFrame(rows).to_csv(self.output_dir / filename, index=False, encoding="utf-8-sig")

    def plot_equity_curve(self, equity_curve: pd.Series, filename: str) -> None:
        plt.figure(figsize=(12, 6))
        plt.plot(equity_curve.index, equity_curve.values, label="Equity")
        plt.title("Equity Curve")
        plt.xlabel("Date")
        plt.ylabel("Account Equity")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(self.output_dir / filename, dpi=150)
        plt.close()


def calculate_report(equity_curve: pd.Series, trades: list[Trade], initial_cash: float) -> BacktestReport:
    """根据资金曲线和交易记录计算绩效指标。"""
    equity_curve = equity_curve.dropna()
    if equity_curve.empty:
        return BacktestReport(0, 0, 0, 0, 0, 0, 0)

    total_return = equity_curve.iloc[-1] / initial_cash - 1
    days = max((equity_curve.index[-1] - equity_curve.index[0]).days, 1)
    annual_return = (1 + total_return) ** (365 / days) - 1

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    max_drawdown = float(drawdown.min())

    daily_returns = equity_curve.pct_change().dropna()
    sharpe_ratio = 0.0
    if daily_returns.std(ddof=0) > 0:
        sharpe_ratio = float((daily_returns.mean() / daily_returns.std(ddof=0)) * np.sqrt(252))

    returns = np.array([trade.return_pct for trade in trades], dtype=float)
    trade_count = len(returns)
    win_rate = float((returns > 0).mean()) if trade_count else 0.0

    wins = returns[returns > 0]
    losses = returns[returns < 0]
    if len(wins) and len(losses):
        avg_profit_loss_ratio = float(wins.mean() / abs(losses.mean()))
    elif len(wins):
        avg_profit_loss_ratio = float("inf")
    else:
        avg_profit_loss_ratio = 0.0

    return BacktestReport(
        total_return=float(total_return),
        annual_return=float(annual_return),
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        win_rate=win_rate,
        avg_profit_loss_ratio=avg_profit_loss_ratio,
        trade_count=trade_count,
    )
