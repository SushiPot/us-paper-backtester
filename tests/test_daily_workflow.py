import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests
from sklearn.dummy import DummyClassifier

from src.prediction import _fit_or_load, _latest_state, _training_code_fingerprint, run_prediction
from src.prediction_data import PredictionConfig, PredictionDataStore, file_hash, write_json
from src.prediction_features import FEATURES, build_dataset, time_partitions
from test_prediction import market_frames


class DailyModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = PredictionConfig(symbols=("AAA", "BBB"), start="2018-01-01", min_symbols=2,
                                       min_train_dates=100, min_eval_dates=100,
                                       output_dir=Path(self.temp.name), cache_dir=Path(self.temp.name) / "cache")
        self.frames = market_frames()
        self.data = build_dataset(self.frames, self.config)
        self.parts = time_partitions(self.data, self.config)
        model = DummyClassifier(strategy="prior").fit(self.parts["train"][FEATURES], self.parts["train"].target.astype(int))
        self.fit_result = (model, "dummy", .55, .5, pd.DataFrame({"model": ["dummy"]}), pd.DataFrame({"threshold": [.55]}))

    def test_reporting_and_line_endings_do_not_invalidate_training_code(self):
        import src.prediction as prediction

        source = Path(prediction.__file__).read_text(encoding="utf-8")
        expected = _training_code_fingerprint(source)
        self.assertEqual(expected, _training_code_fingerprint(source + "\ndef another_report():\n    return 'new report'\n"))
        self.assertEqual(expected, _training_code_fingerprint(source.replace("\n", "\r\n")))
        self.assertNotEqual(expected, _training_code_fingerprint(source.replace("C=0.1", "C=0.2")))
        with self.assertRaisesRegex(ValueError, "missing"):
            _training_code_fingerprint("def another_report():\n    return 1\n")

    def test_model_reuse_depends_on_training_validation_and_checksum_not_forward_data(self):
        with patch("src.prediction.fit_select", return_value=self.fit_result) as fit:
            first = _fit_or_load(self.parts, self.config, "first")
            self.assertEqual(first[-1], "TRAINED")
            self.parts["forward"] = self.parts["forward"].iloc[:10].copy()
            self.assertEqual(_fit_or_load(self.parts, self.config, "new-forward")[-1], "REUSED")
            self.assertEqual(fit.call_count, 1)
            for partition in ("train", "validation"):
                self.parts[partition] = self.parts[partition].copy()
                self.parts[partition].iloc[0, self.parts[partition].columns.get_loc(FEATURES[0])] += .01
                self.assertEqual(_fit_or_load(self.parts, self.config, "changed")[-1], "TRAINED")
            (self.config.output_dir / "model.joblib").write_bytes(b"broken")
            self.assertEqual(_fit_or_load(self.parts, self.config, "changed")[-1], "TRAINED")
            self.assertEqual(fit.call_count, 4)

    def test_daily_skips_historical_simulation_and_preserves_issued_forecast(self):
        as_of = self.frames["SPY"].index[-1]
        inventory = pd.DataFrame({"symbol": list(self.frames), "status": "CURRENT", "sha256": "test"})
        quotes = pd.DataFrame(columns=["symbol", "price", "currency", "quote_at", "quote_status", "source", "error"])
        with patch("src.prediction.PredictionDataStore.load", return_value=(self.frames, inventory)), \
             patch("src.prediction.PredictionDataStore.quotes", return_value=quotes), \
             patch("src.prediction.completed_session", return_value=as_of), \
             patch("src.prediction.fit_select", return_value=self.fit_result), \
             patch("src.prediction.compare_execution", side_effect=AssertionError("must not backtest daily")), \
             patch("src.prediction.execution_sensitivity", side_effect=AssertionError("must not sweep daily")):
            result = run_prediction(self.config, daily=True)
            snapshot = self.config.output_dir / "issued" / f"{as_of.date()}.json"
            original = snapshot.read_bytes()
            second = run_prediction(self.config, daily=True)
        self.assertEqual(result["mode"], "DAILY")
        self.assertEqual(second["model_action"], "REUSED")
        self.assertEqual(snapshot.read_bytes(), original)
        self.assertFalse((self.config.output_dir / "execution_trades.csv").exists())
        self.assertFalse(second["trading_enabled"])

    def test_download_then_csv_cache_reuses_identical_training_inputs(self):
        as_of = self.frames["SPY"].index[-1]

        def response_for(url, **kwargs):
            frame = self.frames[url.rsplit("/", 1)[-1]]
            timestamps = (frame.index.tz_localize("America/New_York") + pd.Timedelta(hours=10)).as_unit("s").asi8.tolist()
            payload = {"chart": {"result": [{"timestamp": timestamps, "indicators": {
                "quote": [{column: frame[column].tolist() for column in frame.columns}],
                "adjclose": [{"adjclose": frame.close.tolist()}]}}]}}
            response = Mock(status_code=200, headers={})
            response.json.return_value = payload
            return response

        with patch("src.prediction_data.requests.Session") as session, patch("src.prediction_data.time.sleep"):
            get = session.return_value.__enter__.return_value.get
            get.side_effect = response_for
            downloaded, _ = PredictionDataStore(self.config).load(refresh=True, as_of=as_of)
            cached, _ = PredictionDataStore(self.config).load(as_of=as_of)
            self.assertEqual(get.call_count, 3)
        parts = time_partitions(build_dataset(downloaded, self.config), self.config)
        reread_parts = time_partitions(build_dataset(cached, self.config), self.config)
        for partition in ("train", "validation"):
            pd.testing.assert_frame_equal(parts[partition][FEATURES], reread_parts[partition][FEATURES], check_exact=True)
            for column in ("date", "label_end"):
                pd.testing.assert_series_equal(parts[partition][column].dt.as_unit("us"),
                                               reread_parts[partition][column].dt.as_unit("us"), check_exact=True)
        with patch("src.prediction.fit_select", return_value=self.fit_result) as fit:
            first = _fit_or_load(parts, self.config, "same-price-files")
            second = _fit_or_load(reread_parts, self.config, "same-price-files")
            self.assertEqual(first[-1], "TRAINED")
            self.assertEqual(second[-1], "REUSED")
            self.assertEqual(first[2], second[2])
            self.assertEqual(fit.call_count, 1)

    def test_datetime_resolution_does_not_invalidate_or_mutate_training_inputs(self):
        # Construct every representation explicitly instead of relying on parser defaults.
        with patch("src.prediction.fit_select", return_value=self.fit_result) as fit:
            first = _fit_or_load(self.parts, self.config, "original")
            self.assertEqual(first[-1], "TRAINED")
            for unit in ("s", "ms", "us", "ns"):
                with self.subTest(unit=unit):
                    converted = {name: frame.copy() for name, frame in self.parts.items()}
                    for partition in ("train", "validation"):
                        for column in ("date", "label_end"):
                            converted[partition][column] = converted[partition][column].dt.as_unit(unit)
                    result = _fit_or_load(converted, self.config, "different-serialization")
                    self.assertEqual(result[-1], "REUSED")
                    self.assertEqual(result[2], first[2])
                    for partition in ("train", "validation"):
                        for column in ("date", "label_end"):
                            self.assertEqual(converted[partition][column].dtype, f"datetime64[{unit}]")
            self.assertEqual(fit.call_count, 1)

    def test_latest_state_blocks_stale_data_and_missed_open(self):
        as_of = self.frames["SPY"].index[-1]
        inventory = pd.DataFrame({"symbol": list(self.frames), "status": "CURRENT"})
        model = self.fit_result[0]
        with patch("src.prediction.now_new_york", return_value=pd.Timestamp("2030-01-01", tz="America/New_York").to_pydatetime()):
            _, ready, context = _latest_state(self.data, inventory, model, .55, self.config, as_of)
            self.assertTrue(ready)
            self.assertEqual(context["action"], "WAIT_FOR_NEXT_CLOSE")
            inventory.loc[0, "status"] = "STALE"
            _, ready, context = _latest_state(self.data, inventory, model, .55, self.config, as_of)
            self.assertFalse(ready)
            self.assertEqual(context["action"], "WAIT_FOR_FRESH_DATA")

    def test_latest_state_reports_no_signal_before_the_next_open(self):
        as_of = self.frames["SPY"].index[-1]
        inventory = pd.DataFrame({"symbol": list(self.frames), "status": "CURRENT"})
        clock = (as_of.tz_localize("America/New_York") + pd.Timedelta(hours=22)).to_pydatetime()
        with patch("src.prediction.now_new_york", return_value=clock):
            _, ready, context = _latest_state(self.data, inventory, self.fit_result[0], 1.0, self.config, as_of)
        self.assertTrue(ready)
        self.assertEqual(context["action"], "NO_QUALIFIED_SIGNAL")
        self.assertEqual(context["qualified_signal_count"], 0)


class DailyNetworkTests(unittest.TestCase):
    def test_verified_cache_preserves_exact_float_values_across_download_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(cache_dir=Path(tmp))
            frame = market_frames(150)["AAA"]
            path = Path(tmp) / "AAA.csv"
            frame.to_csv(path, index_label="date")
            write_json(path.with_suffix(".json"), {"schema": 1, "symbol": "AAA",
                "price_basis": "dividend_split_adjusted", "sha256": file_hash(path)})
            read, _ = PredictionDataStore(config).read("AAA")
            pd.testing.assert_frame_equal(frame, read, check_exact=True, check_freq=False, check_names=False)

    def test_transport_failure_stops_remaining_history_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(symbols=("AAA", "BBB"), cache_dir=Path(tmp), request_interval=0)
            with patch("src.prediction_data.requests.Session") as session, patch("src.prediction_data.time.sleep"):
                get = session.return_value.__enter__.return_value.get
                get.side_effect = requests.ConnectionError("offline")
                _, inventory = PredictionDataStore(config).load(refresh=True, as_of="2026-10-19")
                self.assertEqual(get.call_count, 2)
                self.assertTrue((inventory.status == "MISSING").all())
            self.assertIn("Network unavailable", PredictionDataStore(config).blocked_reason)

    def test_provider_retry_after_can_extend_the_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(cache_dir=Path(tmp))
            response = Mock(status_code=429, headers={"Retry-After": "7200"})
            response.raise_for_status.side_effect = requests.HTTPError("429")
            with self.assertRaises(requests.HTTPError):
                PredictionDataStore(config)._check_response(response)
            state = json.loads((Path(tmp) / "network_state.json").read_text())
            self.assertGreater((pd.Timestamp(state["until"]) - pd.Timestamp.now("UTC")).total_seconds(), 7100)

    def test_rate_limit_persists_across_restarts_and_quotes_share_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(cache_dir=Path(tmp), request_interval=0)
            response = Mock(status_code=429)
            response.raise_for_status.side_effect = requests.HTTPError("429")
            with patch("src.prediction_data.requests.Session") as session:
                get = session.return_value.__enter__.return_value.get
                get.return_value = response
                PredictionDataStore(config).quotes(["SPY", "AAA"], refresh=True)
                PredictionDataStore(config).quotes(["BBB"], refresh=True)
                self.assertEqual(get.call_count, 1)
            self.assertTrue((Path(tmp) / "network_state.json").exists())

    def test_malformed_and_future_cached_quotes_are_not_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = PredictionConfig(cache_dir=Path(tmp))
            (Path(tmp) / "quotes.json").write_text(json.dumps({"AAA": [], "BBB": {
                "price": 10, "quote_at": "2099-01-01T00:00:00Z", "fetched_at": "2099-01-01T00:00:00Z"},
                "CCC": {"price": 10, "quote_at": None}}))
            quotes = PredictionDataStore(config).quotes(["AAA", "BBB", "CCC"])
            self.assertEqual(quotes.quote_status.tolist(), ["MISSING", "MISSING", "MISSING"])
            self.assertTrue(quotes.price.isna().all())


class DailyWebTests(unittest.TestCase):
    def test_home_is_lazy_and_keeps_highest_ranked_rows(self):
        from src.web_app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "prediction").mkdir()
            pd.DataFrame({"symbol": [f"R{i:02}" for i in range(20)], "probability": [.9 - i / 100 for i in range(20)]}).to_csv(root / "prediction/latest_predictions.csv", index=False)
            (root / "signal_evaluation.csv").write_text("invalid,huge,legacy-file")
            original = pd.read_csv
            def read(path, *args, **kwargs):
                self.assertNotEqual(Path(path).name, "signal_evaluation.csv")
                return original(path, *args, **kwargs)
            with patch("src.web_app.pd.read_csv", side_effect=read):
                client = create_app(root).test_client()
                response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"R00", response.data)
            self.assertIn(b"R09", response.data)
            self.assertNotIn(b"R19", response.data)
            self.assertNotIn(b"Run AI Manager", response.data)
            self.assertEqual(client.get("/health").json["service"], "us-paper-backtester")

    def test_reports_are_allowlisted_and_paginated(self):
        from src.web_app import create_app, _csv_page

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "signal_evaluation.csv"
            pd.DataFrame({"value": range(251)}).to_csv(path, index=False)
            frame, following = _csv_page(path, 2)
            self.assertEqual(frame.value.tolist(), list(range(100, 200)))
            self.assertTrue(following)
            frame, following = _csv_page(path, 3)
            self.assertEqual(len(frame), 51)
            self.assertFalse(following)
            client = create_app(root).test_client()
            self.assertEqual(client.get("/reports/signals?page=2").status_code, 200)
            self.assertEqual(client.get("/reports/secrets").status_code, 404)
            self.assertEqual(client.get("/reports/signals?page=0").status_code, 400)
            self.assertEqual(client.get("/advanced").status_code, 200)

    def test_daily_scheduler_profile_skips_legacy_work(self):
        import self_update_main as workflow

        with patch("sys.argv", ["self_update_main.py", "--daily", "--with-prediction", "--skip-tests", "--force-local-paper"]), \
             patch.object(workflow, "_run_prediction") as prediction, \
             patch.object(workflow, "_run_cache") as cache, \
             patch.object(workflow, "_run_daemon") as daemon, \
             patch.object(workflow, "_run_dashboard") as dashboard:
            workflow.main()
        prediction.assert_called_once()
        cache.assert_not_called()
        daemon.assert_not_called()
        dashboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
