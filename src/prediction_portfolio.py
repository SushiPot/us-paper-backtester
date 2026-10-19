"""Cash-funded execution research with an explicit daily marked portfolio."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .prediction_data import PredictionConfig


EXECUTION_PROTOCOL = {
    "version": "staggered_v1",
    "status": "EXPLORATORY",
    "trading_enabled": False,
    "selection": "Original model and threshold; descending probability, symbol tie-break",
    "baseline": "One cash book; up to top_k positions every horizon sessions",
    "staggered": "min(horizon, top_k) initially equal cash books; one position per book",
    "schedule": "Exchange-session offsets modulo horizon; exit before entry at the same open",
    "limits": "No borrowing; no concurrent duplicate symbols; at most top_k names; entry spend <= equity/top_k",
    "costs": "Half round-trip basis points on each buy/sell; stress doubles both fees",
    "valuation": "Adjusted opens each session; missing held prices invalidate the experiment",
    "evidence": "Already inspected historical periods; prospective validation still required",
}


class PortfolioDataError(ValueError):
    pass


@dataclass
class _Lot:
    symbol: str
    book: int
    shares: float
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    entry_cash: float
    entry_fee: float
    entry_equity: float


def simulate_execution(scored: pd.DataFrame, frames: dict[str, pd.DataFrame], threshold: float,
                       config: PredictionConfig, *, mode: str, cost_multiplier: float = 1.0):
    """Decisions use probabilities and calendar dates, never future outcome availability."""
    if (mode not in {"baseline", "staggered"} or not np.isfinite(cost_multiplier) or cost_multiplier < 0
            or not np.isfinite(config.cost_bps) or not 0 <= threshold <= 1):
        raise ValueError("Invalid execution mode or cost multiplier")
    if scored.empty or "SPY" not in frames:
        raise PortfolioDataError("Execution research requires signals and SPY prices")
    if (scored.duplicated(["date", "symbol"]).any() or not np.isfinite(scored.probability).all()
            or not scored.probability.between(0, 1).all()):
        raise ValueError("Invalid or duplicate prediction rows")
    calendar = frames["SPY"].index
    schedule = {}
    for date, group in scored.groupby("date", sort=True):
        if group.entry_date.nunique() != 1 or group.label_end.nunique() != 1:
            raise PortfolioDataError("Signals for a session must share entry and exit dates")
        entry, exit_date = group.entry_date.iloc[0], group.label_end.iloc[0]
        if date not in calendar or entry not in calendar or exit_date not in calendar:
            raise PortfolioDataError("Incomplete execution calendar")
        if calendar.get_loc(entry) != calendar.get_loc(date) + 1 or calendar.get_loc(exit_date) != calendar.get_loc(entry) + config.horizon:
            raise PortfolioDataError("Entry or exit disagrees with the exchange-session horizon")
        schedule[entry] = (exit_date, group.loc[group.probability >= threshold].sort_values(
            ["probability", "symbol"], ascending=[False, True]))
    start = min(schedule)
    end = max(item[0] for item in schedule.values())
    days = calendar[(calendar >= start) & (calendar <= end)]
    opens = pd.DataFrame({symbol: prices.open.reindex(days) for symbol, prices in frames.items()})

    def quote(symbol, day):
        value = opens.at[day, symbol] if symbol in opens else np.nan
        if not np.isfinite(value) or value <= 0:
            raise PortfolioDataError(f"Missing executable/held price: {symbol} {day.date()}")
        return float(value)

    books = 1 if mode == "baseline" else min(config.horizon, config.top_k)
    cash = np.full(books, 1.0 / books)
    positions: dict[str, _Lot] = {}
    trades, equity_rows = [], []
    fee = config.cost_bps / 20000 * cost_multiplier
    if fee >= 1:
        raise ValueError("Execution costs must be less than trade proceeds")
    spy_shares = 1 / (quote("SPY", start) * (1 + fee))
    for offset, day in enumerate(days):
        fees = 0.0
        for symbol, lot in list(positions.items()):
            if lot.exit_date != day:
                continue
            price = quote(symbol, day)
            exit_fee = lot.shares * price * fee
            proceeds = lot.shares * price - exit_fee
            cash[lot.book] += proceeds
            fees += exit_fee
            trades.append({"symbol": symbol, "book": lot.book, "entry_date": lot.entry_date,
                           "exit_date": day, "entry_cash": lot.entry_cash, "exit_cash": proceeds,
                           "entry_price": lot.entry_price, "exit_price": price, "shares": lot.shares,
                           "entry_equity": lot.entry_equity, "entry_fee": lot.entry_fee, "exit_fee": exit_fee,
                           "net_return": proceeds / lot.entry_cash - 1,
                           "pnl": proceeds - lot.entry_cash, "fees": lot.entry_fee + exit_fee})
            del positions[symbol]
        marked = {symbol: lot.shares * quote(symbol, day) for symbol, lot in positions.items()}
        before = float(cash.sum() + sum(marked.values()))
        phase = offset % config.horizon
        book = 0 if mode == "baseline" else phase
        scheduled = phase == 0 if mode == "baseline" else book < books
        if day in schedule and scheduled and not any(lot.book == book for lot in positions.values()):
            exit_date, candidates = schedule[day]
            slots = config.top_k if mode == "baseline" else 1
            slot_budget = float(cash[book]) / slots
            remaining_slots = min(slots, config.top_k - len(positions))
            for item in candidates.itertuples():
                if remaining_slots <= 0:
                    break
                if item.symbol in positions:
                    continue
                price = quote(item.symbol, day)
                spend = min(slot_budget, before / config.top_k, float(cash[book]))
                if spend <= 1e-12:
                    continue
                shares = spend / (price * (1 + fee))
                entry_fee = shares * price * fee
                cash[book] -= spend
                fees += entry_fee
                positions[item.symbol] = _Lot(item.symbol, book, shares, day, exit_date, price, spend, entry_fee, before)
                marked[item.symbol] = shares * price
                remaining_slots -= 1
        value = float(sum(marked.values()))
        equity = float(cash.sum() + value)
        if not np.isfinite(equity) or cash.min() < -1e-10 or len(positions) > config.top_k or equity <= 0:
            raise RuntimeError("Execution cash/position invariant failed")
        spy_equity = spy_shares * quote("SPY", day) * ((1 - fee) if day == end else 1)
        equity_rows.append({"date": day, "equity": equity, "cash": float(cash.sum()),
                            "market_value": value, "exposure": value / equity,
                            "positions": len(positions), "fees": fees,
                            "max_name_weight": max(marked.values(), default=0) / equity,
                            "spy_equity": spy_equity})
    if positions:
        raise RuntimeError("Execution research ended with unfinished positions")
    columns = ["symbol", "book", "entry_date", "exit_date", "entry_cash", "exit_cash", "entry_price",
               "exit_price", "shares", "entry_equity", "entry_fee", "exit_fee", "net_return", "pnl", "fees"]
    return pd.DataFrame(equity_rows), pd.DataFrame(trades, columns=columns)


def execution_metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict:
    nav = equity.equity.to_numpy()
    peaks = np.maximum.accumulate(np.r_[1.0, nav])[1:]
    wins = trades.loc[trades.pnl > 0]
    losses = trades.loc[trades.pnl < 0]
    loss_cash = abs(float(losses.pnl.sum()))
    return {"total_return": float(nav[-1] - 1), "max_drawdown": float((nav / peaks - 1).min()),
            "trades": len(trades), "winning_trades": len(wins),
            "trade_win_rate": len(wins) / len(trades) if len(trades) else None,
            "average_win": float(wins.net_return.mean()) if len(wins) else None,
            "average_loss": float(losses.net_return.mean()) if len(losses) else None,
            "profit_factor": float(wins.pnl.sum()) / loss_cash if loss_cash else None,
            "total_fees": float(equity.fees.sum()), "mean_exposure": float(equity.exposure.mean()),
            "max_exposure": float(equity.exposure.max()), "max_positions": int(equity.positions.max()),
            "max_name_weight": float(equity.max_name_weight.max()),
            "min_cash": float(equity.cash.min()), "spy_buy_hold_return": float(equity.spy_equity.iloc[-1] - 1),
            "valuation_sessions": len(equity)}


def compare_execution(scored: pd.DataFrame, frames: dict, threshold: float, config: PredictionConfig):
    metrics, curves, all_trades = [], [], []
    for mode in ("baseline", "staggered"):
        curve, trades = simulate_execution(scored, frames, threshold, config, mode=mode)
        stress, _ = simulate_execution(scored, frames, threshold, config, mode=mode, cost_multiplier=2)
        metrics.append({"mode": mode, **execution_metrics(curve, trades),
                        "stress_total_return": float(stress.equity.iloc[-1] - 1)})
        curves.append(curve.assign(mode=mode))
        all_trades.append(trades.assign(mode=mode))
    return pd.DataFrame(metrics), pd.concat(curves, ignore_index=True), pd.concat(all_trades, ignore_index=True)


def execution_sensitivity(scored: pd.DataFrame, frames: dict, threshold: float, config: PredictionConfig) -> pd.DataFrame:
    dates = sorted(scored.date.unique())
    rows = []
    for offset in range(min(config.horizon, len(dates))):
        subset = scored.loc[scored.date >= dates[offset]]
        for mode in ("baseline", "staggered"):
            equity, trades = simulate_execution(subset, frames, threshold, config, mode=mode)
            result = execution_metrics(equity, trades)
            rows.append({"start_offset": offset, "mode": mode,
                         **{key: result[key] for key in ("total_return", "max_drawdown", "trade_win_rate", "trades")}})
    return pd.DataFrame(rows)
