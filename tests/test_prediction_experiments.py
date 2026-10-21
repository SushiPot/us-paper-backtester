from copy import deepcopy
from importlib.util import find_spec
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier

from src.prediction_data import PredictionConfig, file_hash, write_json
from src.prediction_experiment_features import ENRICHED_FEATURES, build_experiment_dataset
from src.prediction_experiments import (calibrate, checked_probabilities, completed_report,
                                        development_folds, fitting_segments, freeze_registration,
                                        load_protocol, make_model, run_experiments, score_candidate, summarize)
from test_prediction import market_frames
from src.prediction_volatility import SOURCES


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "config/prediction_experiment_v1.json"


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.protocol = load_protocol(PROTOCOL_PATH)
        self.config = PredictionConfig(symbols=("AAA", "BBB"), start="2018-01-01",
                                       min_train_dates=100, min_symbols=2)

    def small_protocol(self):
        protocol = deepcopy(self.protocol)
        protocol.update(evaluation_years=[2022, 2023], minimum_fit_dates=100, minimum_symbols=2)
        return protocol

    def test_factors_are_finite_and_future_changes_cannot_rewrite_past(self):
        frames = market_frames(150)
        cutoff = frames["SPY"].index[100]
        first, coverage = build_experiment_dataset(frames, self.config)
        self.assertEqual(coverage["enriched_features"], 59)
        self.assertEqual(len(ENRICHED_FEATURES), len(set(ENRICHED_FEATURES)))
        self.assertTrue(np.isfinite(first[ENRICHED_FEATURES]).all().all())
        for frame in frames.values():
            frame.loc[frame.index > cutoff, ["open", "high", "low", "close", "volume"]] *= 2
        second, _ = build_experiment_dataset(frames, self.config)
        pd.testing.assert_frame_equal(first.loc[first.date <= cutoff, ENRICHED_FEATURES],
                                      second.loc[second.date <= cutoff, ENRICHED_FEATURES])
        row = first.loc[(first.symbol == "AAA") & (first.date == cutoff)].iloc[0]
        bar = frames["AAA"].loc[cutoff]
        self.assertAlmostEqual(row.bar_body, (bar.close - bar.open) / bar.open)

    def test_zero_range_and_volume_do_not_generate_infinities(self):
        frames = market_frames(150)
        for frame in frames.values():
            frame["volume"] = 1
            frame["open"] = frame["high"] = frame["low"] = frame["close"]
        data, _ = build_experiment_dataset(frames, self.config)
        self.assertTrue(np.isfinite(data[ENRICHED_FEATURES]).all().all())
        self.assertTrue((data.body_range == 0).all())

    def test_fold_boundaries_purge_future_labels_and_exclude_test_years(self):
        data, _ = build_experiment_dataset(market_frames(), self.config)
        for year, train, evaluate in development_folds(data, self.small_protocol()):
            self.assertLess(train.label_end.max(), evaluate.date.min())
            self.assertEqual(set(evaluate.date.dt.year), {year})
            self.assertLessEqual(evaluate.label_end.max(), pd.Timestamp(year, 12, 31))
            self.assertLessEqual(evaluate.date.max(), pd.Timestamp("2023-12-31"))
            raw = self.protocol["candidates"][-2]
            fit, calibration = fitting_segments(train, year, raw, self.small_protocol())
            self.assertEqual(calibration.date.nunique(), 126)
            self.assertLess(fit.label_end.max(), calibration.date.min())
            self.assertLess(calibration.label_end.max(), evaluate.date.min())
            calibrated_fit, calibrated_segment = fitting_segments(train, year, self.protocol["candidates"][-1], self.small_protocol())
            pd.testing.assert_frame_equal(fit, calibrated_fit)
            pd.testing.assert_frame_equal(calibration, calibrated_segment)

    def test_protocol_refuses_later_years_or_duplicate_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocol.json"
            for mutation in ("future", "duplicate"):
                protocol = deepcopy(self.protocol)
                if mutation == "future":
                    protocol["evaluation_years"].append(2024)
                else:
                    protocol["candidates"].append(protocol["candidates"][0])
                write_json(path, protocol)
                with self.assertRaises(ValueError):
                    load_protocol(path)

    def test_calibration_requires_positive_slope_and_valid_probabilities(self):
        values = np.linspace(.1, .9, 100)
        calibrated = calibrate(values, (values >= .5).astype(int), values, self.protocol)
        self.assertTrue((np.diff(calibrated) > 0).all())
        with self.assertRaisesRegex(ValueError, "monotonically"):
            calibrate(values, (values < .5).astype(int), values, self.protocol)
        with self.assertRaisesRegex(ValueError, "two target classes"):
            calibrate(values, np.zeros(100), values, self.protocol)
        for invalid in ([.1, np.nan], [.2, 1.1], [[.1], [.2]], [.2]):
            with self.assertRaisesRegex(ValueError, "Invalid model probabilities"):
                checked_probabilities(invalid, 2)

    @unittest.skipUnless(find_spec("lightgbm"), "Optional research dependency not installed")
    def test_real_lightgbm_engine_is_deterministic_with_fixed_parameters(self):
        data, _ = build_experiment_dataset(market_frames(500), self.config)
        train, evaluate = data.iloc[:600], data.iloc[600:700]
        parameters = deepcopy(self.protocol)
        parameters["models"]["lightgbm"].update(n_estimators=5, min_child_samples=20)
        first, second = make_model("lightgbm", parameters), make_model("lightgbm", parameters)
        first.fit(train[ENRICHED_FEATURES], train.target.astype(int))
        second.fit(train[ENRICHED_FEATURES], train.target.astype(int))
        values = first.predict_proba(evaluate[ENRICHED_FEATURES])[:, 1]
        np.testing.assert_array_equal(values, second.predict_proba(evaluate[ENRICHED_FEATURES])[:, 1])
        checked_probabilities(values, len(evaluate))

    def test_scores_retain_every_phase_and_do_not_confuse_coverage_with_accuracy(self):
        data, _ = build_experiment_dataset(market_frames(150), self.config)
        data = data.loc[data.complete_outcomes].dropna(subset=["target"])
        result = score_candidate(data, np.full(len(data), .54), .5, self.config, .55)
        self.assertEqual(result["metrics"]["signal_count"], 0)
        self.assertIsNone(result["metrics"]["signal_hit_rate"])
        self.assertEqual([row["phase"] for row in result["starting_phases"]], list(range(5)))
        self.assertEqual(sum(row["count"] for row in result["reliability"]), len(data))

    def test_gates_reject_one_bad_year_or_phase_and_never_promote(self):
        rows = []
        for candidate in self.protocol["candidates"]:
            for year in self.protocol["evaluation_years"]:
                phases = [{"phase": phase, "trades": 60, "active_blocks": 30,
                           "stress_total_return": .1, "max_drawdown": -.05} for phase in range(5)]
                rows.append({"candidate": candidate["name"], "year": year, "status": "COMPLETE",
                             "metrics": {"brier_skill": .01}, "starting_phases": phases})
        self.assertTrue(all(row["status"] == "DEVELOPMENT_ONLY_SHADOW_REVIEW" for row in summarize(rows, self.protocol)))
        rows[0]["starting_phases"][-1]["stress_total_return"] = -.01
        result = summarize(rows, self.protocol)
        self.assertEqual(result[0]["status"], "REJECTED_DEVELOPMENT")
        self.assertFalse(any(row["policy_changed"] or row["trading_enabled"] for row in result))
        rows[1]["starting_phases"].pop()
        self.assertIn("incomplete_starting_phases", summarize(rows, self.protocol)[0]["reasons"])

    def test_registration_and_completed_evidence_are_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            original = {"input_key": "a", "protocol": {"threshold": .55}}
            freeze_registration(directory, original)
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                freeze_registration(directory, {**original, "protocol": {"threshold": .6}})
            write_json(directory / "report.json", {"input_key": "a"})
            write_json(directory / "completion.json", {"input_key": "a", "files": {"report.json": file_hash(directory / "report.json")}})
            self.assertEqual(completed_report(directory, "a"), {"input_key": "a"})
            write_json(directory / "report.json", {"input_key": "tampered"})
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                completed_report(directory, "a")

    def test_volatility_inputs_use_same_rows_and_ignore_future_changes(self):
        protocol = load_protocol(PROTOCOL_PATH.with_name("prediction_experiment_volatility_v2.json"))
        protocol.update(evaluation_years=[2022, 2023], minimum_fit_dates=100, minimum_symbols=2)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            path = root / "protocol.json"
            write_json(path, protocol)
            frames = market_frames()
            for symbol, frame in frames.items():
                price = cache / f"{symbol}.csv"
                frame.to_csv(price, index_label="date")
                write_json(price.with_suffix(".json"), {"schema": 1, "symbol": symbol,
                           "price_basis": "dividend_split_adjusted", "sha256": file_hash(price)})
            config = PredictionConfig(symbols=("AAA", "BBB"), cache_dir=cache)
            calendar = frames["SPY"].index
            external = {name: pd.DataFrame({"close": 20 + np.arange(len(calendar)) / 100},
                                           index=calendar) for name in SOURCES}
            external["VIX9D"] = external["VIX9D"].iloc[100:]
            with patch("src.prediction_experiments.PredictionConfig", return_value=config), \
                    patch("src.prediction_experiments.CboeHistoryStore") as store, \
                    patch("src.prediction_experiments.make_model", side_effect=lambda *args: DummyClassifier(strategy="prior")) as factory:
                store.return_value.load.return_value = external, []
                result = run_experiments(path, root / "experiments")
                for year in (2022, 2023):
                    folds = [row for row in result["folds"] if row["year"] == year and row["round"] == 1]
                    self.assertEqual(len(folds), 2)
                    self.assertEqual({row["status"] for row in folds}, {"COMPLETE"})
                    self.assertEqual(folds[0]["training_rows"], folds[1]["training_rows"])
                    self.assertEqual(folds[0]["metrics"]["rows"], folds[1]["metrics"]["rows"])
                    self.assertEqual([row["features"] for row in folds], [12, 20])
                count = factory.call_count
                for frame in external.values():
                    frame.loc[frame.index >= "2024-01-01", "close"] *= 2
                self.assertEqual(run_experiments(path, root / "experiments")["input_key"], result["input_key"])
                self.assertEqual(factory.call_count, count)
                external["VIX"].loc[calendar[500], "close"] += .01
                changed = run_experiments(path, root / "experiments")
                self.assertNotEqual(changed["input_key"], result["input_key"])
                self.assertGreater(factory.call_count, count)

    def test_offline_runner_freezes_before_fit_preserves_failures_and_reuses_exact_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            cache.mkdir()
            protocol_path = root / "protocol.json"
            write_json(protocol_path, self.small_protocol())
            frames = market_frames()
            for symbol, frame in frames.items():
                path = cache / f"{symbol}.csv"
                frame.to_csv(path, index_label="date")
                write_json(path.with_suffix(".json"), {"schema": 1, "symbol": symbol,
                           "price_basis": "dividend_split_adjusted", "sha256": file_hash(path)})
            config = PredictionConfig(symbols=("AAA", "BBB"), start="2018-01-01", cache_dir=cache,
                                       output_dir=root / "active")

            def model_factory(name, protocol):
                self.assertEqual(len(list((root / "experiments").glob("*/registration.json"))), 1)
                if name == "lightgbm":
                    raise ImportError("test missing optional dependency")
                return DummyClassifier(strategy="prior")

            with patch("src.prediction_experiments.PredictionConfig", return_value=config), \
                    patch("src.prediction_experiments.make_model", side_effect=model_factory) as factory, \
                    patch("src.prediction_data.requests.Session", side_effect=AssertionError("No network allowed")):
                result = run_experiments(protocol_path, root / "experiments")
                self.assertEqual(len(result["folds"]), 12)
                self.assertEqual(result["status"], "COMPLETE_WITH_FAILURES")
                self.assertEqual(sum(row["status"] == "FAILED" for row in result["folds"]), 8)
                count = factory.call_count
                reused = run_experiments(protocol_path, root / "experiments")
                self.assertEqual(factory.call_count, count)
                self.assertEqual(reused["input_key"], result["input_key"])
                for symbol, frame in frames.items():
                    frame.loc[frame.index >= "2024-01-01", ["open", "high", "low", "close"]] *= 1.01
                    path = cache / f"{symbol}.csv"
                    frame.to_csv(path, index_label="date")
                    write_json(path.with_suffix(".json"), {"schema": 1, "symbol": symbol,
                               "price_basis": "dividend_split_adjusted", "sha256": file_hash(path)})
                after_future_change = run_experiments(protocol_path, root / "experiments")
                self.assertEqual(after_future_change["input_key"], result["input_key"])
                self.assertEqual(factory.call_count, count)
                self.assertFalse((root / "active").exists())
                directory = root / "experiments" / result["input_key"]
                (directory / "completion.json").unlink()
                interrupted = run_experiments(protocol_path, root / "experiments")
                self.assertEqual(factory.call_count, count)
                self.assertEqual(interrupted["input_key"], result["input_key"])
                (directory / "completion.json").unlink()
                fold = directory / "core_logistic_expanding-2022.json"
                altered = json.loads(fold.read_text(encoding="utf-8"))
                altered["status"] = "CHANGED"
                write_json(fold, altered)
                with self.assertRaisesRegex(ValueError, "Saved fold checksum mismatch"):
                    run_experiments(protocol_path, root / "experiments")


if __name__ == "__main__":
    unittest.main()
