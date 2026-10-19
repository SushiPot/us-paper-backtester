import unittest

import numpy as np
import pandas as pd

from src.prediction import block_metrics
from src.prediction_audit import hit_metrics, phase_audit, validation_folds
from src.prediction_data import PredictionConfig
from src.prediction_features import build_dataset
from test_prediction import market_frames


class HitRateAuditTests(unittest.TestCase):
    def test_hit_rate_includes_costs_flat_trades_and_top_k(self):
        config = PredictionConfig(top_k=4)
        data = pd.DataFrame({"date": pd.to_datetime(["2022-01-03"] * 5),
                             "entry_date": pd.to_datetime(["2022-01-04"] * 5),
                             "label_end": pd.to_datetime(["2022-01-11"] * 5),
                             "symbol": list("ABCDE"), "probability": [.8, .8, .8, .8, .6],
                             "gross_return": [.012, -.008, .002, .004, .5], "spy_return": .01})
        data["target"] = (data.gross_return > .002).astype(float)
        result = hit_metrics(data, .55, config)
        self.assertEqual(result["trades"], 4)
        self.assertEqual(result["winning_trades"], 2)
        self.assertEqual(result["losing_trades"], 1)
        self.assertEqual(result["trade_win_rate"], .5)
        self.assertEqual(result["signal_hit_rate"], .6)
        self.assertAlmostEqual(result["average_win"], .006)
        self.assertAlmostEqual(result["average_loss"], -.01)
        self.assertAlmostEqual(result["profit_factor"], 1.2)
        self.assertIsNone(hit_metrics(data, .9, config)["trade_win_rate"])
        self.assertIsNone(block_metrics(pd.DataFrame(), config)["trade_win_rate"])

    def test_validation_refits_cannot_see_test_or_cross_boundary_labels(self):
        config = PredictionConfig(symbols=("AAA", "BBB"), start="2018-01-01",
                                  min_symbols=2, min_train_dates=100, min_eval_dates=100)
        data = build_dataset(market_frames(), config)
        original = list(validation_folds(data, config, 5))
        mutated = data.copy()
        mutated.loc[mutated.date >= "2024-01-01", "target"] = np.nan
        again = list(validation_folds(mutated, config, 5))
        self.assertEqual([fold[0] for fold in original], [2022, 2023])
        for (year, train, evaluate), (_, train_again, eval_again) in zip(original, again):
            boundary = pd.Timestamp(year=year, month=1, day=1)
            self.assertLess(train.label_end.max(), boundary)
            self.assertGreaterEqual(train.date.min(), boundary - pd.DateOffset(years=5))
            self.assertLessEqual(evaluate.label_end.max(), pd.Timestamp(f"{year}-12-31"))
            pd.testing.assert_frame_equal(train, train_again)
            pd.testing.assert_frame_equal(evaluate, eval_again)

    def test_every_starting_phase_is_reported_and_first_matches_baseline(self):
        config = PredictionConfig(symbols=("AAA", "BBB"))
        data = build_dataset(market_frames(150), config).dropna(subset=["target"]).assign(probability=.6)
        result = phase_audit(data, .55, config)
        self.assertEqual(result.phase.to_list(), [0, 1, 2, 3, 4])
        self.assertEqual(result.iloc[0].trade_win_rate, hit_metrics(data, .55, config)["trade_win_rate"])


if __name__ == "__main__":
    unittest.main()
