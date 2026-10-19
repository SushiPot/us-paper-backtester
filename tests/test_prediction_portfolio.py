from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from src.prediction_data import PredictionConfig
from src.prediction_portfolio import PortfolioDataError, compare_execution, execution_sensitivity, simulate_execution


def execution_fixture(horizon=2):
    calendar = pd.bdate_range("2024-01-02", periods=12)
    frames = {}
    for symbol, price in (("SPY", np.full(12, 100.0)), ("AAA", np.arange(100., 112.)),
                          ("BBB", np.arange(112., 100., -1)), ("CCC", np.full(12, 100.0))):
        frames[symbol] = pd.DataFrame({"open": price}, index=calendar)
    rows = [{"date": date, "entry_date": calendar[i + 1], "label_end": calendar[i + horizon + 1],
             "symbol": symbol, "probability": score, "target": np.nan, "gross_return": np.nan}
            for i, date in enumerate(calendar[:8])
            for symbol, score in (("AAA", .9), ("BBB", .8), ("CCC", .7))]
    config = PredictionConfig(symbols=("AAA", "BBB", "CCC"), horizon=horizon, top_k=2)
    return pd.DataFrame(rows), frames, config


class PredictionExecutionTests(unittest.TestCase):
    def test_cash_conservation_fees_and_position_limits(self):
        data, frames, config = execution_fixture()
        for mode in ("baseline", "staggered"):
            with self.subTest(mode=mode):
                equity, trades = simulate_execution(data, frames, .55, config, mode=mode)
                self.assertTrue((equity.cash >= -1e-10).all())
                self.assertTrue((equity.exposure <= 1 + 1e-10).all())
                self.assertLessEqual(equity.positions.max(), 2)
                self.assertTrue(np.allclose(equity.cash + equity.market_value, equity.equity))
                self.assertEqual(equity.iloc[-1].positions, 0)
                self.assertAlmostEqual(equity.equity.iloc[-1], 1 + trades.pnl.sum())
                self.assertAlmostEqual(equity.fees.sum(), trades.fees.sum())
                self.assertTrue((trades.entry_cash <= trades.entry_equity / config.top_k + 1e-10).all())
                for _, group in trades.groupby("symbol"):
                    group = group.sort_values("entry_date")
                    self.assertTrue((group.entry_date.iloc[1:].to_numpy() >= group.exit_date.iloc[:-1].to_numpy()).all())

    def test_round_trip_costs_are_paid_on_actual_buy_and_sell(self):
        data, frames, config = execution_fixture(horizon=1)
        config = replace(config, top_k=1)
        data = data.iloc[:1]
        for frame in frames.values():
            frame.loc[:, "open"] = 100.0
        summary, curves, trades = compare_execution(data, frames, .55, config)
        fee = config.cost_bps / 20000
        expected = (1 - fee) / (1 + fee) - 1
        self.assertTrue(np.allclose(summary.total_return, expected))
        self.assertTrue(np.allclose(trades.net_return, expected))
        self.assertTrue((summary.stress_total_return < summary.total_return).all())
        self.assertLess(curves.equity.iloc[0], 1)

    def test_unknown_or_modified_outcomes_do_not_change_execution(self):
        data, frames, config = execution_fixture()
        first, trades = simulate_execution(data, frames, .55, config, mode="staggered")
        data["target"], data["gross_return"], data["complete_outcomes"] = 1, 1000, False
        second, again = simulate_execution(data, frames, .55, config, mode="staggered")
        pd.testing.assert_frame_equal(first, second)
        pd.testing.assert_frame_equal(trades, again)

    def test_missing_held_price_invalidates_instead_of_removing_loser(self):
        data, frames, config = execution_fixture()
        frames["AAA"].iloc[2, 0] = np.nan
        with self.assertRaisesRegex(PortfolioDataError, "AAA"):
            simulate_execution(data, frames, .55, config, mode="staggered")

    def test_future_price_changes_do_not_change_past_nav_or_orders(self):
        data, frames, config = execution_fixture()
        cutoff = frames["SPY"].index[5]
        before, orders = simulate_execution(data, frames, .55, config, mode="staggered")
        for frame in frames.values():
            frame.loc[frame.index > cutoff, "open"] *= 2
        after, later_orders = simulate_execution(data, frames, .55, config, mode="staggered")
        pd.testing.assert_frame_equal(before.loc[before.date <= cutoff], after.loc[after.date <= cutoff])
        columns = ["symbol", "book", "entry_date", "entry_cash", "entry_fee"]
        pd.testing.assert_frame_equal(orders.loc[orders.entry_date <= cutoff, columns].reset_index(drop=True),
                                      later_orders.loc[later_orders.entry_date <= cutoff, columns].reset_index(drop=True))

    def test_cash_only_when_no_signal_has_no_artificial_win_rate(self):
        data, frames, config = execution_fixture()
        summary, curves, trades = compare_execution(data, frames, .99, config)
        self.assertTrue(trades.empty)
        self.assertTrue(summary.trade_win_rate.isna().all())
        self.assertTrue((summary.total_return == 0).all())
        self.assertTrue((curves.cash == 1).all())

    def test_invalid_calendar_is_rejected(self):
        data, frames, config = execution_fixture()
        data.loc[data.date == data.date.min(), "label_end"] = frames["SPY"].index[2]
        with self.assertRaisesRegex(PortfolioDataError, "horizon"):
            simulate_execution(data, frames, .55, config, mode="staggered")

    def test_horizon_longer_than_position_limit_never_adds_extra_books(self):
        data, frames, config = execution_fixture()
        config = replace(config, top_k=1)
        equity, trades = simulate_execution(data, frames, .55, config, mode="staggered")
        self.assertEqual(trades.book.nunique(), 1)
        self.assertLessEqual(equity.positions.max(), 1)

    def test_sensitivity_reports_all_offsets_without_selecting_a_winner(self):
        data, frames, config = execution_fixture()
        result = execution_sensitivity(data, frames, .55, config)
        self.assertEqual(len(result), config.horizon * 2)
        self.assertEqual(set(zip(result.start_offset, result["mode"])),
                         {(offset, mode) for offset in (0, 1) for mode in ("baseline", "staggered")})
        equity, _ = simulate_execution(data, frames, .55, config, mode="staggered")
        initial = result.loc[(result.start_offset == 0) & (result["mode"] == "staggered")].iloc[0]
        self.assertAlmostEqual(initial.total_return, equity.equity.iloc[-1] - 1)


if __name__ == "__main__":
    unittest.main()
