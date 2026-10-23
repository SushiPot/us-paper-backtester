from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.prediction_data import PredictionConfig, file_hash, write_json
from src.prediction_experiments import (development_folds, load_protocol, make_model,
                                        run_experiments, score_candidate, summarize)
from src.prediction_features import FEATURES, build_dataset
from test_prediction import market_frames


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "config/prediction_experiment_identity_v3.json"


class StockIdentityTests(unittest.TestCase):
    def setUp(self):
        self.protocol = load_protocol(PROTOCOL_PATH)
        self.config = PredictionConfig(symbols=("AAA", "BBB"))

    def test_identity_encoder_learns_only_fit_symbols_and_handles_unseen_stock(self):
        data = pd.DataFrame(0., index=range(200), columns=FEATURES)
        data["symbol"] = ["AAA"] * 100 + ["BBB"] * 100
        targets = np.array([1] * 90 + [0] * 10 + [1] * 10 + [0] * 90)
        model = make_model("symbol_logistic", self.protocol)
        model.fit(data, targets)
        encoder = model.steps[0][1].named_transformers_["stock"]
        self.assertEqual(encoder.categories_[0].tolist(), ["AAA", "BBB"])
        future = data.iloc[:3].copy()
        future["symbol"] = ["AAA", "BBB", "NEW"]
        probability = model.predict_proba(future)[:, 1]
        self.assertGreater(probability[0], probability[1])
        self.assertTrue(np.isfinite(probability).all())
        self.assertEqual(encoder.categories_[0].tolist(), ["AAA", "BBB"])
        np.testing.assert_array_equal(encoder.transform(pd.DataFrame({"symbol": ["NEW"]})), [[0., 0.]])

    def test_stock_prior_comparison_and_unseen_fallback_use_supplied_fit_priors(self):
        data = build_dataset(market_frames(150), self.config).dropna(subset=["target"]).iloc[:3].copy()
        data["symbol"], data["target"], data["gross_return"] = ["AAA", "BBB", "NEW"], [1., 0., 1.], [.02, -.01, .03]
        result = score_candidate(data, [.5] * 3, .6, self.config, .55, symbol_priors={"AAA": .9, "BBB": .1})
        metrics = result["metrics"]
        expected = (.1 ** 2 + .1 ** 2 + .4 ** 2) / 3
        self.assertAlmostEqual(metrics["symbol_prior_brier"], expected)
        self.assertAlmostEqual(metrics["symbol_prior_brier_skill"], 1 - .25 / expected)
        self.assertEqual(metrics["symbol_prior_unseen_rows"], 1)
        result = score_candidate(data, [.5] * 3, .6, self.config, .55,
                                 symbol_priors={"AAA": 1., "BBB": 0., "NEW": 1.})
        self.assertEqual(result["metrics"]["symbol_prior_brier"], 0.)
        self.assertIsNone(result["metrics"]["symbol_prior_brier_skill"])

    def test_global_prior_pass_cannot_hide_failure_against_stock_prior(self):
        rows = [{"candidate": candidate["name"], "year": year, "status": "COMPLETE",
                 "metrics": {"brier_skill": .01, "symbol_prior_brier_skill": .01},
                 "starting_phases": [{"phase": phase, "trades": 60, "active_blocks": 30,
                                      "stress_total_return": .1, "max_drawdown": -.05} for phase in range(5)]}
                for candidate in self.protocol["candidates"] for year in self.protocol["evaluation_years"]]
        self.assertTrue(all(row["status"] == "DEVELOPMENT_ONLY_SHADOW_REVIEW" for row in summarize(rows, self.protocol)))
        for value in (-.01, None):
            rows[0]["metrics"]["symbol_prior_brier_skill"] = value
            result = summarize(rows, self.protocol)
            self.assertEqual(result[0]["status"], "REJECTED_DEVELOPMENT")
            self.assertIn("stock_prior_baseline_not_beaten_every_year", result[0]["reasons"])
            self.assertFalse(result[0]["policy_changed"] or result[0]["trading_enabled"])

    def test_single_declared_pair_requires_registered_round_and_stock_comparison(self):
        self.assertEqual(len(self.protocol["candidates"]), 2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocol.json"
            for field, value in (("rounds", [1, 2]), ("rounds", []), ("symbol_prior_comparison", False)):
                broken = deepcopy(self.protocol)
                broken[field] = value
                write_json(path, broken)
                with self.assertRaises(ValueError):
                    load_protocol(path)
            broken = deepcopy(self.protocol)
            broken["candidates"][1]["features"] = "enriched"
            write_json(path, broken)
            with self.assertRaises(ValueError):
                load_protocol(path)

    def test_real_pair_is_purged_matched_offline_and_reused_after_future_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            protocol = deepcopy(self.protocol)
            protocol.update(evaluation_years=[2022, 2023], minimum_fit_dates=100, minimum_symbols=2)
            path = root / "protocol.json"
            write_json(path, protocol)
            frames = market_frames()

            def save_prices():
                for symbol, frame in frames.items():
                    price = cache / f"{symbol}.csv"
                    frame.to_csv(price, index_label="date")
                    write_json(price.with_suffix(".json"), {"schema": 1, "symbol": symbol,
                               "price_basis": "dividend_split_adjusted", "sha256": file_hash(price)})

            save_prices()
            config = PredictionConfig(symbols=("AAA", "BBB"), cache_dir=cache, output_dir=root / "active")
            outputs = root / "experiments"

            def factory(name, registered):
                self.assertEqual(len(list(outputs.glob("*/registration.json"))), 1)
                return make_model(name, registered)

            with patch("src.prediction_experiments.PredictionConfig", return_value=config), \
                    patch("src.prediction_experiments.make_model", side_effect=factory) as fitting, \
                    patch("src.prediction_experiments.build_experiment_dataset", side_effect=AssertionError("No enriched-row filtering")), \
                    patch("src.prediction_data.requests.Session", side_effect=AssertionError("No network")):
                result = run_experiments(path, outputs)
                self.assertEqual(result["status"], "COMPLETE")
                self.assertEqual(len(result["folds"]), 4)
                truncated = {symbol: frame.loc[frame.index <= "2023-12-31"] for symbol, frame in frames.items()}
                for year, train, evaluate in development_folds(build_dataset(truncated, config), protocol):
                    folds = [row for row in result["folds"] if row["year"] == year]
                    self.assertEqual(folds[0]["training_rows"], folds[1]["training_rows"])
                    self.assertEqual(folds[0]["metrics"]["rows"], folds[1]["metrics"]["rows"])
                    self.assertEqual([row["features"] for row in folds], [12, 13])
                    expected = ((evaluate.symbol.map(train.groupby("symbol").target.mean()) - evaluate.target) ** 2).mean()
                    for row in folds:
                        self.assertLess(pd.Timestamp(row["training_last_label"]), pd.Timestamp(row["evaluation_first"]))
                        self.assertAlmostEqual(row["metrics"]["symbol_prior_brier"], expected)
                count = fitting.call_count
                for frame in frames.values():
                    frame.loc[frame.index >= "2024-01-01", ["open", "high", "low", "close"]] *= 1.01
                save_prices()
                self.assertEqual(run_experiments(path, outputs)["input_key"], result["input_key"])
                self.assertEqual(fitting.call_count, count)
            self.assertFalse((root / "active").exists())
            report = (outputs / result["input_key"] / "report.md").read_text()
            self.assertIn("2 fixed candidates", report)
            self.assertIn("Stock-prior skill", report)


if __name__ == "__main__":
    unittest.main()
