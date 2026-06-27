from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .database import get_store
from .portfolio import Trade
from .risk import RiskEvent


@dataclass(frozen=True)
class BacktestReport:
    """???????"""

    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    avg_profit_loss_ratio: float
    trade_count: int


class ReportWriter:
    """??????????????????"""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_trade_log(self, trades: list[Trade], filename: str) -> None:
        rows = [
            {
                "????": trade.trade_time,
                "????": trade.symbol,
                "????": trade.buy_price,
                "????": trade.sell_price,
                "??": trade.shares,
                "???": trade.return_pct,
                "????": trade.account_balance,
                "????": trade.reason,
                "????": trade.strategy_name,
                "????": trade.signal_score,
                "??RSI": _metric(trade.entry_metrics, "rsi"),
                "?????": _metric(trade.entry_metrics, "ma_gap_pct"),
                "?????": _metric(trade.entry_metrics, "volume_ratio"),
                "??MA??": _metric(trade.entry_metrics, "distance_fast_ma"),
                "??5???": _metric(trade.entry_metrics, "return_5d"),
                "??RSI": _metric(trade.exit_metrics, "rsi"),
                "?????": _metric(trade.exit_metrics, "ma_gap_pct"),
            }
            for trade in trades
        ]
        pd.DataFrame(rows).to_csv(self.output_dir / filename, index=False, encoding="utf-8-sig")

    def write_backtest_strategy_scorecard(self, trades: list[Trade], filename: str) -> None:
        """????????????"""
        rows = []
        for strategy_name in sorted({trade.strategy_name for trade in trades}):
            strategy_trades = [trade for trade in trades if trade.strategy_name == strategy_name]
            returns = np.array([trade.return_pct for trade in strategy_trades], dtype=float)
            wins = returns[returns > 0]
            losses = returns[returns < 0]
            avg_profit_loss_ratio = float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else 0.0
            invested = sum(trade.buy_price * trade.shares for trade in strategy_trades)
            pnl = sum((trade.sell_price - trade.buy_price) * trade.shares for trade in strategy_trades)
            rows.append(
                {
                    "strategy_name": strategy_name,
                    "trade_count": len(strategy_trades),
                    "win_rate": float((returns > 0).mean()) if len(returns) else 0.0,
                    "avg_return": float(returns.mean()) if len(returns) else 0.0,
                    "best_return": float(returns.max()) if len(returns) else 0.0,
                    "worst_return": float(returns.min()) if len(returns) else 0.0,
                    "avg_profit_loss_ratio": avg_profit_loss_ratio,
                    "gross_invested": invested,
                    "realized_pnl": pnl,
                    "avg_signal_score": float(np.mean([trade.signal_score for trade in strategy_trades])) if strategy_trades else 0.0,
                    "avg_entry_rsi": float(np.mean([_metric(trade.entry_metrics, "rsi") for trade in strategy_trades]))
                    if strategy_trades
                    else 0.0,
                    "avg_entry_volume_ratio": float(np.mean([_metric(trade.entry_metrics, "volume_ratio") for trade in strategy_trades]))
                    if strategy_trades
                    else 0.0,
                }
            )
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values(["realized_pnl", "win_rate"], ascending=[False, False])
        frame.to_csv(self.output_dir / filename, index=False, encoding="utf-8-sig")
        get_store().append_generic_frame("backtest_strategy_scorecard", filename, frame)

    def write_report(self, report: BacktestReport, filename: str) -> None:
        row = {
            "????": report.total_return,
            "?????": report.annual_return,
            "????": report.max_drawdown,
            "????": report.sharpe_ratio,
            "??": report.win_rate,
            "?????": report.avg_profit_loss_ratio,
            "????": report.trade_count,
        }
        pd.DataFrame([row]).to_csv(self.output_dir / filename, index=False, encoding="utf-8-sig")
        get_store().append_report(
            filename,
            {
                "total_return": report.total_return,
                "annual_return": report.annual_return,
                "max_drawdown": report.max_drawdown,
                "sharpe_ratio": report.sharpe_ratio,
                "win_rate": report.win_rate,
                "avg_profit_loss_ratio": report.avg_profit_loss_ratio,
                "trade_count": report.trade_count,
            },
        )

    def write_equity_curve_csv(self, equity_curve: pd.Series, filename: str) -> None:
        """??????????????????????"""
        frame = pd.DataFrame({"date": equity_curve.index, "equity": equity_curve.values})
        frame.to_csv(self.output_dir / filename, index=False, encoding="utf-8-sig")

    def write_risk_log(self, events: list[RiskEvent], filename: str) -> None:
        rows = [
            {
                "????": event.event_time,
                "??": event.reason,
                "????": event.equity,
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
    """??????????????????"""
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


def _metric(metrics: dict[str, object], key: str) -> float:
    try:
        value = metrics.get(key, 0.0)
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0
