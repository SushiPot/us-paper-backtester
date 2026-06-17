from __future__ import annotations

import pandas as pd

from .config import BacktestConfig
from .data import MarketDataLoader
from .indicators import add_indicators
from .portfolio import Portfolio
from .performance import PerformanceReportBuilder
from .report import BacktestReport, ReportWriter, calculate_report
from .risk import RiskManager
from .strategy import evaluate_buy_signal, should_sell_by_signal


class Backtester:
    """事件驱动式日线回测，只模拟成交，不包含真实下单接口。"""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.portfolio = Portfolio(config.initial_cash)
        self.risk = RiskManager(config.daily_loss_limit_pct, config.max_account_drawdown_pct)
        self.report_writer = ReportWriter(config.output_dir)

    def run(self) -> BacktestReport:
        raw_data = MarketDataLoader(self.config).download_all()
        data = {
            symbol: add_indicators(frame, self.config.fast_ma, self.config.slow_ma, self.config.rsi_period)
            for symbol, frame in raw_data.items()
        }
        calendar = self._build_calendar(data)

        equity_points: list[tuple[pd.Timestamp, float]] = []
        previous_equity: float | None = None

        for date in calendar:
            prices = self._get_prices_for_date(data, date)
            if not prices:
                continue

            equity_before = self.portfolio.total_equity(prices)
            self.risk.update(date, equity_before, previous_equity)

            self._process_sells(date, data, prices)

            if self.risk.can_open_new_positions:
                self._process_buys(date, data, prices)

            equity_after = self.portfolio.total_equity(prices)
            equity_points.append((date, equity_after))
            previous_equity = equity_after

        equity_curve = pd.Series(
            data=[point[1] for point in equity_points],
            index=[point[0] for point in equity_points],
            name="equity",
        )
        report = calculate_report(equity_curve, self.portfolio.trades, self.config.initial_cash)

        self.report_writer.write_trade_log(self.portfolio.trades, self.config.trade_log_file)
        self.report_writer.write_risk_log(self.risk.events, self.config.risk_log_file)
        self.report_writer.write_report(report, self.config.report_file)
        self.report_writer.write_equity_curve_csv(equity_curve, self.config.equity_curve_csv_file)
        self.report_writer.plot_equity_curve(equity_curve, self.config.equity_curve_file)
        PerformanceReportBuilder(self.config.output_dir).build_from_series(
            equity_curve,
            self.config.performance_report_file,
            self.config.performance_metrics_file,
            "US Paper Backtester Performance Report",
        )
        if self.risk.stop_reason:
            print(self.risk.stop_reason)
        return report

    @staticmethod
    def _build_calendar(data: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
        dates = sorted(set().union(*(frame.index for frame in data.values())))
        return pd.DatetimeIndex(dates)

    @staticmethod
    def _get_prices_for_date(data: dict[str, pd.DataFrame], date: pd.Timestamp) -> dict[str, float]:
        prices: dict[str, float] = {}
        for symbol, frame in data.items():
            if date in frame.index:
                close = frame.at[date, "close"]
                if pd.notna(close):
                    prices[symbol] = float(close)
        return prices

    def _process_sells(
        self,
        date: pd.Timestamp,
        data: dict[str, pd.DataFrame],
        prices: dict[str, float],
    ) -> None:
        for symbol in list(self.portfolio.positions.keys()):
            if symbol not in prices or date not in data[symbol].index:
                continue

            position = self.portfolio.positions[symbol]
            row = data[symbol].loc[date]
            price = prices[symbol]
            return_pct = position.return_pct(price)
            holding_days = self._count_holding_days(data[symbol], position.entry_date, date)

            reason = ""
            if should_sell_by_signal(row):
                reason = "MA20下穿MA60"
            elif return_pct <= self.config.stop_loss_pct:
                reason = "止损"
            elif return_pct >= self.config.take_profit_pct:
                reason = "止盈"
            elif holding_days > self.config.max_holding_days:
                reason = "持仓超过30个交易日"

            if reason:
                trade = self.portfolio.sell(symbol, date, price, 0.0, reason)
                trade.account_balance = self.portfolio.total_equity(prices)

    def _process_buys(
        self,
        date: pd.Timestamp,
        data: dict[str, pd.DataFrame],
        prices: dict[str, float],
    ) -> None:
        if len(self.portfolio.positions) >= self.config.max_positions:
            return

        equity = self.portfolio.total_equity(prices)
        for symbol in self.config.symbols:
            if len(self.portfolio.positions) >= self.config.max_positions:
                break
            if symbol in self.portfolio.positions or symbol not in prices or date not in data[symbol].index:
                continue

            row = data[symbol].loc[date]
            buy_evaluation = evaluate_buy_signal(
                row,
                rsi_limit=self.config.rsi_limit,
                enabled_strategies=self.config.enabled_buy_strategies,
                trend_min_rsi=self.config.trend_min_rsi,
                trend_volume_ratio=self.config.trend_volume_ratio,
                trend_max_distance_fast_ma=self.config.trend_max_distance_fast_ma,
                trend_min_return_5d=self.config.trend_min_return_5d,
            )
            if buy_evaluation.should_buy:
                max_position_pct = self.config.special_max_position_pct.get(symbol, self.config.max_position_pct)
                if buy_evaluation.strategy_name == "trend_follow":
                    max_position_pct *= self.config.trend_position_scale
                max_amount = equity * max_position_pct
                self.portfolio.buy(symbol, date, prices[symbol], max_amount)

    @staticmethod
    def _count_holding_days(frame: pd.DataFrame, entry_date: pd.Timestamp, current_date: pd.Timestamp) -> int:
        mask = (frame.index > entry_date) & (frame.index <= current_date)
        return int(mask.sum())
