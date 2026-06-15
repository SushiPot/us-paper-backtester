from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BacktestConfig
from .data import MarketDataLoader
from .indicators import calculate_rsi


@dataclass(frozen=True)
class StrategyParams:
    fast_ma: int
    slow_ma: int
    rsi_period: int
    rsi_limit: float
    stop_loss_pct: float
    take_profit_pct: float
    max_holding_days: int

    @property
    def label(self) -> str:
        return (
            f"ma{self.fast_ma}_{self.slow_ma}_rsi{self.rsi_period}_{int(self.rsi_limit)}_"
            f"sl{abs(int(self.stop_loss_pct * 100))}_tp{int(self.take_profit_pct * 100)}_h{self.max_holding_days}"
        )


@dataclass(frozen=True)
class OptimizationResult:
    params_label: str
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    trade_count: int
    win_rate: float


class ParameterOptimizer:
    """Run a small parameter sweep without replacing the main backtester."""

    def __init__(self, config: BacktestConfig | None = None, output_dir: Path = Path("outputs")) -> None:
        self.config = config or BacktestConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> OptimizationResult:
        raw_data = MarketDataLoader(self.config).download_all()
        params_grid = self._default_grid()
        results = []

        for params in params_grid:
            data = {symbol: self._add_indicators(frame, params) for symbol, frame in raw_data.items()}
            result = self._simulate(data, params)
            results.append(result)

        frame = pd.DataFrame([result.__dict__ for result in results])
        frame = frame.sort_values(["sharpe_ratio", "total_return"], ascending=[False, False])
        frame.to_csv(self.output_dir / "optimization_results.csv", index=False, encoding="utf-8-sig")
        frame.head(10).to_csv(self.output_dir / "optimization_top10.csv", index=False, encoding="utf-8-sig")
        best = frame.iloc[0]
        return OptimizationResult(
            params_label=str(best["params_label"]),
            total_return=float(best["total_return"]),
            annual_return=float(best["annual_return"]),
            max_drawdown=float(best["max_drawdown"]),
            sharpe_ratio=float(best["sharpe_ratio"]),
            trade_count=int(best["trade_count"]),
            win_rate=float(best["win_rate"]),
        )

    @staticmethod
    def _default_grid() -> list[StrategyParams]:
        params = []
        for fast_ma, slow_ma, rsi_limit, stop_loss, take_profit, hold_days in product(
            [10, 20, 30],
            [50, 60, 120],
            [60, 70],
            [-0.05, -0.08],
            [0.15, 0.20, 0.30],
            [20, 30],
        ):
            if fast_ma >= slow_ma:
                continue
            params.append(
                StrategyParams(
                    fast_ma=fast_ma,
                    slow_ma=slow_ma,
                    rsi_period=14,
                    rsi_limit=rsi_limit,
                    stop_loss_pct=stop_loss,
                    take_profit_pct=take_profit,
                    max_holding_days=hold_days,
                )
            )
        return params

    @staticmethod
    def _add_indicators(data: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
        result = data.copy()
        result["fast_ma"] = result["close"].rolling(params.fast_ma).mean()
        result["slow_ma"] = result["close"].rolling(params.slow_ma).mean()
        result["volume_ma20"] = result["volume"].rolling(20).mean()
        result["rsi"] = calculate_rsi(result["close"], params.rsi_period)
        prev_fast = result["fast_ma"].shift(1)
        prev_slow = result["slow_ma"].shift(1)
        result["golden_cross"] = (prev_fast <= prev_slow) & (result["fast_ma"] > result["slow_ma"])
        result["death_cross"] = (prev_fast >= prev_slow) & (result["fast_ma"] < result["slow_ma"])
        return result

    def _simulate(self, data: dict[str, pd.DataFrame], params: StrategyParams) -> OptimizationResult:
        cash = self.config.initial_cash
        positions: dict[str, dict] = {}
        trades: list[float] = []
        equity_points: list[tuple[pd.Timestamp, float]] = []
        calendar = pd.DatetimeIndex(sorted(set().union(*(frame.index for frame in data.values()))))

        for date in calendar:
            prices = {
                symbol: float(frame.at[date, "close"])
                for symbol, frame in data.items()
                if date in frame.index and pd.notna(frame.at[date, "close"])
            }
            if not prices:
                continue

            for symbol in list(positions.keys()):
                if symbol not in prices or date not in data[symbol].index:
                    continue
                position = positions[symbol]
                row = data[symbol].loc[date]
                price = prices[symbol]
                return_pct = price / position["entry_price"] - 1
                holding_days = int(((data[symbol].index > position["entry_date"]) & (data[symbol].index <= date)).sum())
                should_sell = (
                    bool(row["death_cross"])
                    or return_pct <= params.stop_loss_pct
                    or return_pct >= params.take_profit_pct
                    or holding_days > params.max_holding_days
                )
                if should_sell:
                    cash += position["shares"] * price
                    trades.append(return_pct)
                    del positions[symbol]

            equity = cash + sum(position["shares"] * prices.get(symbol, position["entry_price"]) for symbol, position in positions.items())
            max_amount = equity * self.config.max_position_pct
            for symbol in self.config.symbols:
                if len(positions) >= self.config.max_positions:
                    break
                if symbol in positions or symbol not in prices or date not in data[symbol].index:
                    continue
                row = data[symbol].loc[date]
                buy_signal = bool(
                    row["golden_cross"]
                    and row["rsi"] < params.rsi_limit
                    and row["volume"] > row["volume_ma20"]
                )
                if not buy_signal:
                    continue
                shares = int(min(max_amount, cash) // prices[symbol])
                if shares <= 0:
                    continue
                cash -= shares * prices[symbol]
                positions[symbol] = {"shares": shares, "entry_price": prices[symbol], "entry_date": date}

            equity = cash + sum(position["shares"] * prices.get(symbol, position["entry_price"]) for symbol, position in positions.items())
            equity_points.append((date, equity))

        equity_curve = pd.Series([point[1] for point in equity_points], index=[point[0] for point in equity_points])
        return self._calculate_result(params, equity_curve, trades)

    def _calculate_result(
        self,
        params: StrategyParams,
        equity_curve: pd.Series,
        trades: list[float],
    ) -> OptimizationResult:
        if equity_curve.empty:
            return OptimizationResult(params.label, 0.0, 0.0, 0.0, 0.0, 0, 0.0)

        total_return = float(equity_curve.iloc[-1] / self.config.initial_cash - 1)
        days = max((equity_curve.index[-1] - equity_curve.index[0]).days, 1)
        annual_return = float((1 + total_return) ** (365 / days) - 1)
        drawdown = equity_curve / equity_curve.cummax() - 1
        max_drawdown = float(drawdown.min())
        returns = equity_curve.pct_change().dropna()
        sharpe = float((returns.mean() / returns.std(ddof=0)) * np.sqrt(252)) if returns.std(ddof=0) > 0 else 0.0
        trade_count = len(trades)
        win_rate = float((np.array(trades) > 0).mean()) if trades else 0.0
        return OptimizationResult(params.label, total_return, annual_return, max_drawdown, sharpe, trade_count, win_rate)
