from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from src.prediction import block_metrics, evaluate_issued, portfolio_blocks, prediction_lock, record_forecast, run_prediction
from src.prediction_data import PredictionConfig, PredictionDataStore, parse_chart, validate_prices
from src.prediction_features import FEATURES, build_dataset, time_partitions


def market_frames(periods=2200):
    dates = pd.bdate_range("2018-01-02", periods=periods)
    rng = np.random.default_rng(13)
    frames = {}
    for symbol in ("SPY", "AAA", "BBB"):
        close = 100 * np.exp(np.cumsum(rng.normal(.0002, .012, periods)))
        opening = close * np.exp(rng.normal(0, .003, periods))
        frames[symbol] = pd.DataFrame({"open": opening, "high": np.maximum(opening, close) * 1.01,
                                       "low": np.minimum(opening, close) * .99, "close": close,
                                       "volume": rng.integers(10000, 20000, periods)}, index=dates)
    return frames


class PredictionDataTests(unittest.TestCase):
    def test_completed_session_waits_for_close_and_publication_buffer(self):
        from src.market_calendar import completed_session

        for clock, expected in (("08:00", "2026-10-16"), ("16:15", "2026-10-16"), ("16:31", "2026-10-19")):
            with self.subTest(clock=clock), patch("src.market_calendar.now_new_york", return_value=
                    pd.Timestamp(f"2026-10-19 {clock}", tz="America/New_York").to_pydatetime()):
                self.assertEqual(completed_session(), pd.Timestamp(expected))

    def test_health_check_accepts_last_completed_session_after_weekend(self):
        from src.config import BacktestConfig
        from src.data_health import DataHealthChecker

        with tempfile.TemporaryDirectory() as tmp:
            config = BacktestConfig(symbols=["AAA"], cache_dir=Path(tmp))
            checker = DataHealthChecker(config, output_dir=Path(tmp))
            frame = market_frames(150)["AAA"]
            frame.to_csv(Path(tmp) / "AAA.csv", index_label="date")
            latest = frame.index[-1].date()
            with patch("src.data_health.now_new_york", return_value=pd.Timestamp(latest) + pd.Timedelta(days=4)):
                self.assertEqual(checker._check_symbol("AAA", latest)["status"], "OK")
                self.assertEqual(checker._check_symbol("AAA", latest + pd.Timedelta(days=1))["status"], "WARN")
                self.assertEqual(checker._check_symbol("AAA", latest + pd.Timedelta(days=6))["status"], "STALE")

    def test_adjustment_is_applied_to_all_prices_and_incomplete_bar_excluded(self):
        payload = {"chart": {"result": [{"timestamp": [1704205800, 1704292200], "indicators": {
            "quote": [{"open": [100, 102], "high": [110, 112], "low": [90, 92], "close": [100, 102], "volume": [1000, 2000]}],
            "adjclose": [{"adjclose": [50, 51]}],
        }}]}}
        frame = parse_chart(payload, pd.Timestamp("2024-01-02"))
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0].open, 50)
        self.assertEqual(frame.iloc[0].high, 55)
        self.assertEqual(frame.iloc[0].volume, 1000)
        del payload["chart"]["result"][0]["indicators"]["adjclose"]
        with self.assertRaisesRegex(ValueError, "Adjusted close missing"):
            parse_chart(payload, pd.Timestamp("2024-01-02"))

    def test_bad_price_data_is_rejected(self):
        frame = market_frames(100)["AAA"]
        with self.assertRaises(ValueError):
            validate_prices(pd.concat([frame, frame.tail(1)]))
        frame.iloc[5, frame.columns.get_loc("low")] = -1
        with self.assertRaises(ValueError):
            validate_prices(frame)

    def test_http_403_stops_all_remaining_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(symbols=("AAA", "BBB"), cache_dir=Path(tmp), request_interval=0)
            response = Mock(status_code=403)
            import requests
            response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
            with patch("src.prediction_data.requests.Session") as session:
                session.return_value.__enter__.return_value.get.return_value = response
                frames, inventory = PredictionDataStore(config).load(refresh=True, as_of="2026-10-01")
                self.assertEqual(session.return_value.__enter__.return_value.get.call_count, 1)
                self.assertFalse(frames)
                self.assertTrue((inventory.status == "MISSING").all())

    def test_unverified_legacy_cache_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(symbols=("AAA",), cache_dir=Path(tmp))
            market_frames(100)["AAA"].to_csv(Path(tmp) / "AAA.csv", index_label="date")
            with self.assertRaises(FileNotFoundError):
                PredictionDataStore(config).read("AAA")

    def test_reviewed_crisis_move_is_allowed_only_for_exact_symbol_date_and_magnitude(self):
        frame = pd.DataFrame({"open": [9.68, 18.10], "high": [9.68, 18.10], "low": [9.68, 18.10],
                              "close": [9.68, 18.10], "volume": [1000, 2000]},
                             index=pd.to_datetime(["2008-10-10", "2008-10-13"]))
        validate_prices(frame, "MS")
        with self.assertRaises(ValueError):
            validate_prices(frame, "AAA")
        frame.iloc[-1, :4] *= 1.1
        with self.assertRaises(ValueError):
            validate_prices(frame, "MS")

    def test_shorter_cache_window_is_not_reported_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(symbols=("SPY",), cache_dir=Path(tmp))
            frame = market_frames(100)["SPY"]
            with patch.object(PredictionDataStore, "read", return_value=(frame, {"requested_start": "2018-01-01"})):
                _, inventory = PredictionDataStore(config).load(as_of=frame.index[-1])
            self.assertEqual(inventory.iloc[0].status, "STALE")


class PredictionFeatureTests(unittest.TestCase):
    def setUp(self):
        self.config = PredictionConfig(symbols=("AAA", "BBB"), start="2018-01-01", min_symbols=2,
                                       min_train_dates=100, min_eval_dates=100)

    def test_future_changes_do_not_change_past_features(self):
        frames = market_frames()
        cutoff = frames["SPY"].index[1000]
        first = build_dataset(frames, self.config)
        for frame in frames.values():
            frame.loc[frame.index > cutoff, ["open", "high", "low", "close"]] *= 1.2
        second = build_dataset(frames, self.config)
        pd.testing.assert_frame_equal(first.loc[first.date <= cutoff, FEATURES], second.loc[second.date <= cutoff, FEATURES])

    def test_label_is_next_open_to_future_open_and_unknown_labels_stay_missing(self):
        frames = market_frames()
        data = build_dataset(frames, self.config)
        calendar = frames["SPY"].index
        row = data.loc[(data.symbol == "AAA") & (data.date == calendar[100])].iloc[0]
        expected = frames["AAA"].open.iloc[106] / frames["AAA"].open.iloc[101] - 1
        self.assertAlmostEqual(row.gross_return, expected)
        self.assertEqual(row.label_end, calendar[106])
        self.assertTrue(data.loc[data.date == calendar[-1], "target"].isna().all())

    def test_missing_session_is_not_shifted_into_a_different_entry(self):
        frames = market_frames()
        date = frames["AAA"].index[101]
        frames["AAA"] = frames["AAA"].drop(index=date)
        data = build_dataset(frames, self.config)
        row = data.loc[(data.symbol == "AAA") & (data.date == frames["SPY"].index[100])].iloc[0]
        self.assertTrue(pd.isna(row.target))
        self.assertFalse(row.complete_outcomes)
        surviving = data.loc[data.date == row.date].dropna(subset=["target"]).assign(probability=.8)
        self.assertFalse(surviving.empty)
        blocks = portfolio_blocks(surviving, .6, self.config)
        self.assertTrue(blocks.empty)
        self.assertEqual(block_metrics(blocks, self.config)["active_blocks"], 0)

    def test_splits_purge_labels_crossing_boundaries_and_keep_dates_grouped(self):
        data = build_dataset(market_frames(), self.config)
        parts = time_partitions(data, self.config)
        for key, boundary in (("train", self.config.train_end), ("validation", self.config.validation_end), ("test", self.config.test_end)):
            self.assertLessEqual(parts[key].label_end.max(), pd.Timestamp(boundary))
        self.assertLess(parts["train"].label_end.max(), parts["validation"].date.min())
        self.assertLess(parts["validation"].label_end.max(), parts["test"].date.min())
        self.assertFalse(set(parts["train"].date) & set(parts["test"].date))

    def test_portfolio_uses_nonoverlapping_horizons_costs_and_cash(self):
        data = build_dataset(market_frames(150), self.config).dropna(subset=["target"])
        data = data.assign(probability=.8, gross_return=.01, spy_return=.005)
        config = replace(self.config, top_k=2)
        blocks = portfolio_blocks(data, .6, config)
        self.assertTrue(np.allclose(blocks.net_return, .008))
        self.assertTrue(np.allclose(blocks.stress_return, .006))
        self.assertTrue((blocks.entry_date.iloc[1:].to_numpy() >= blocks.exit_date.iloc[:-1].to_numpy()).all())
        cash = portfolio_blocks(data, .9, config)
        self.assertTrue((cash.net_return == 0).all())


class PredictionWorkflowTests(unittest.TestCase):
    def test_issued_forecasts_are_immutable_and_late_forecasts_are_not_prospective(self):
        frames = market_frames(150)
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(symbols=("AAA", "BBB"), output_dir=Path(tmp))
            (Path(tmp) / "model.joblib").write_bytes(b"local-test-model")
            date = frames["SPY"].index[80]
            latest = pd.DataFrame({"symbol": ["AAA", "BBB"], "probability": [.6, .7]})
            record_forecast(latest, config, {}, date)
            path = Path(tmp) / "issued" / f"{date.date()}.json"
            original = path.read_bytes()
            record_forecast(latest.assign(probability=.9), config, {}, date)
            self.assertEqual(original, path.read_bytes())
            dataset = build_dataset(frames, config)
            result = evaluate_issued(dataset, config)
            self.assertEqual(result["mature_rows"], 2)
            self.assertEqual(result["eligible_rows"], 0)
            snapshot = json.loads(original)
            snapshot["issued_at"] = f"{date.date()}T22:00:00+00:00"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = evaluate_issued(dataset, config)
            self.assertEqual(result["eligible_rows"], 2)
            self.assertIsNotNone(result["brier"])

    def test_prediction_status_rejects_non_object_json(self):
        from src.dashboard import SystemStatusBuilder

        with tempfile.TemporaryDirectory() as tmp:
            builder = SystemStatusBuilder(output_dir=Path(tmp))
            (Path(tmp) / "prediction").mkdir()
            (Path(tmp) / "prediction" / "status.json").write_text("[]", encoding="utf-8")
            self.assertEqual(builder._prediction_row()["status"], "INVALID_REPORT")

    def test_self_update_can_run_prediction_without_daemon(self):
        import self_update_main as workflow

        with patch("sys.argv", ["self_update_main.py", "--skip-tests", "--skip-cache", "--skip-daemon", "--with-prediction"]), \
                patch.object(workflow, "_run_prediction") as prediction, \
                patch.object(workflow, "_run_data_health"), patch.object(workflow, "_run_dashboard"), \
                patch.object(workflow, "_print_status_summary"):
            workflow.main()
        prediction.assert_called_once()

    def test_training_outputs_are_reproducible_research_only_and_bounded(self):
        frames = market_frames()
        as_of = frames["SPY"].index[-1]
        inventory = pd.DataFrame([{"symbol": s, "status": "CURRENT", "sha256": s} for s in frames])
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(symbols=("AAA", "BBB"), start="2018-01-01", min_symbols=2,
                                       min_train_dates=100, min_eval_dates=100, output_dir=Path(tmp))
            with patch("src.prediction.completed_session", return_value=as_of), patch(
                "src.prediction.PredictionDataStore.load", return_value=(frames, inventory)
            ):
                report = run_prediction(config)
                first = pd.read_csv(Path(tmp) / "latest_predictions.csv")
                again = run_prediction(config)
                second = pd.read_csv(Path(tmp) / "latest_predictions.csv")
            pd.testing.assert_frame_equal(first, second)
            self.assertEqual(report["metrics"], again["metrics"])
            self.assertFalse(report["trading_enabled"])
            execution = report["execution_research"]
            self.assertFalse(execution["protocol"]["trading_enabled"])
            self.assertFalse(execution["errors"])
            self.assertEqual(len(execution["results"]), 6)
            self.assertTrue(all(row["max_positions"] <= config.top_k for row in execution["results"]))
            self.assertFalse(first.trading_enabled.any())
            self.assertLessEqual(pd.Timestamp(report["metadata"]["training_last_label_date"]), pd.Timestamp(config.train_end))
            self.assertEqual(len(list(Path(tmp).glob("*.joblib"))), 1)
            self.assertTrue((Path(tmp) / "report.md").exists())

    def test_failed_run_replaces_status_with_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(output_dir=Path(tmp))
            with patch("src.prediction.PredictionDataStore.load", side_effect=ValueError("missing verified data")):
                with self.assertRaises(ValueError):
                    run_prediction(config)
            status = json.loads((Path(tmp) / "status.json").read_text())
            self.assertEqual(status["status"], "ERROR")
            self.assertFalse(status["trading_enabled"])

    def test_overlapping_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with prediction_lock(Path(tmp)):
                with self.assertRaises(OSError):
                    with prediction_lock(Path(tmp)):
                        self.fail("Overlapping run obtained lock")


if __name__ == "__main__":
    unittest.main()
