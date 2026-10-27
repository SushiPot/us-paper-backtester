from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.prediction_data import PredictionConfig, file_hash, write_json
from src.prediction_features import FEATURES
from src.prediction_shadow import STUDY, _digest, _protocol, _settings, _sources, _versions
from src.prediction_shadow_health import shadow_health


class ShadowHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = PredictionConfig(symbols=("AAA", "BBB"), top_k=2, output_dir=self.root / "prediction")
        self.study = self.config.output_dir / "shadow" / STUDY
        self.study.mkdir(parents=True)
        (self.study / "model.joblib").write_bytes(b"hash-only fixture; must never deserialize")
        write_json(self.study / "model_manifest.json", {"model_sha256": file_hash(self.study / "model.joblib")})
        self.metadata = {"config": _settings(self.config), "features": FEATURES, "threshold": .55,
                         "training_last_label_date": "2021-12-31"}
        self.record = {"protocol": _protocol(), "settings": _settings(self.config), "sources": _sources(),
                       "versions": _versions(), "model_metadata": self.metadata,
                       "registered_at": "2026-10-16T22:00:00Z", "first_signal_session": "2026-10-16",
                       "files": {name: file_hash(self.study / name) for name in ("model.joblib", "model_manifest.json")}}
        self.save_registration()
        features = [{"symbol": symbol, **dict.fromkeys(FEATURES, 0.)} for symbol in self.config.symbols]
        self.forecast = {"as_of": "2026-10-16", "issued_at": "2026-10-16T22:01:00Z",
                         "model_sha256": self.record["files"]["model.joblib"], "horizon": self.config.horizon,
                         "cost_bps": self.config.cost_bps,
                         "predictions": [{"symbol": symbol, "probability": .75} for symbol in self.config.symbols],
                         "metadata": {**self.metadata, "shadow": {"registration_sha256": _digest(self.record),
                             "feature_inputs": features, "feature_inputs_sha256": _digest(features)}}}
        self.snapshot = self.study / "issued/2026-10-16.json"
        write_json(self.snapshot, self.forecast)
        self.report = {"status": "OBSERVING", "as_of": "2026-10-16", "updated_at": "2026-10-16T22:02:00Z",
                       "registration_sha256": _digest(self.record), "model_sha256": self.record["files"]["model.joblib"],
                       "trading_enabled": False, "policy_changed": False, "prospective": {"outcome_review_days": 0}}
        write_json(self.study / "status.json", self.report)

    def save_registration(self):
        write_json(self.study / "registration.json", {**self.record, "registration_sha256": _digest(self.record)})

    @contextmanager
    def clock(self, now="2026-10-16T22:03:00Z", session="2026-10-16"):
        with patch("src.prediction_shadow_health.now_new_york", return_value=pd.Timestamp(now).to_pydatetime()), \
                patch("src.prediction_shadow_health.completed_session", return_value=pd.Timestamp(session)):
            yield

    def check(self):
        with self.clock():
            return shadow_health(self.config)

    def test_healthy_immature_study_is_read_only_and_never_loads_fits_or_downloads(self):
        original = {p: p.read_bytes() for p in self.study.rglob("*") if p.is_file()}
        with patch("joblib.load", side_effect=AssertionError("No deserialization")), \
                patch("src.prediction.fit_select", side_effect=AssertionError("No training")), \
                patch("requests.Session", side_effect=AssertionError("No network")):
            result = self.check()
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["missing_dates"], [])
        self.assertEqual(original, {p: p.read_bytes() for p in self.study.rglob("*") if p.is_file()})

    def test_optional_unregistered_and_partial_registration_are_distinguished(self):
        config = PredictionConfig(output_dir=self.root / "optional")
        self.assertEqual(shadow_health(config)["status"], "SKIP")
        study = config.output_dir / "shadow" / STUDY
        study.mkdir(parents=True)
        (study / ".run.lock").write_bytes(b"0")
        self.assertEqual(shadow_health(config)["status"], "SKIP")
        (study / "model.joblib").write_bytes(b"partial")
        self.assertEqual(shadow_health(config)["status"], "ERROR")

    def test_missing_forecast_is_pending_before_deadline_and_error_at_deadline(self):
        self.snapshot.unlink()
        result = self.check()
        self.assertEqual(result["status"], "WARN")
        self.assertEqual(result["pending_dates"], ["2026-10-16"])
        with self.clock("2026-10-19T13:30:00Z"):
            result = shadow_health(self.config)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["missing_dates"], ["2026-10-16"])
        self.assertFalse(self.snapshot.exists())

    def test_historical_gaps_remain_visible_even_with_a_fresh_status_report(self):
        self.snapshot.unlink()
        self.report.update(as_of="2026-10-19", updated_at="2026-10-19T22:00:00Z")
        write_json(self.study / "status.json", self.report)
        with self.clock("2026-10-19T22:01:00Z", "2026-10-19"):
            result = shadow_health(self.config)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["missing_dates"], ["2026-10-16"])
        self.assertEqual(result["pending_dates"], ["2026-10-19"])

    def test_registration_after_entry_does_not_invent_a_missed_opportunity(self):
        self.snapshot.unlink()
        self.record["registered_at"] = "2026-10-19T14:00:00Z"
        self.save_registration()
        self.report.update(updated_at="2026-10-19T14:01:00Z", registration_sha256=_digest(self.record))
        write_json(self.study / "status.json", self.report)
        with self.clock("2026-10-19T14:02:00Z"):
            result = shadow_health(self.config)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["missing_dates"], [])

    def test_frozen_artifact_and_environment_drift_fail_without_deserialization(self):
        with patch("src.prediction_shadow_health._versions", return_value={"changed": "version"}):
            self.assertEqual(self.check()["status"], "ERROR")
        (self.study / "model.joblib").write_bytes(b"corrupt")
        result = self.check()
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("checksum mismatch", result["detail"])

    def test_bad_or_stale_status_and_outcome_review_are_errors(self):
        changes = [{"status": "ERROR", "error": "drift"}, {"status": "DATA_REVIEW_REQUIRED"},
                   {"as_of": "2026-10-15"}, {"model_sha256": "different"}, {"registration_sha256": "different"},
                   {"updated_at": "2026-10-16T22:02:00"}, {"updated_at": "2030-01-01T22:00:00Z"},
                   {"trading_enabled": True}, {"prospective": {"outcome_review_days": 1}}]
        for change in changes:
            with self.subTest(change=change):
                write_json(self.study / "status.json", {**self.report, **change})
                self.assertEqual(self.check()["status"], "ERROR")
        (self.study / "status.json").unlink()
        self.assertEqual(self.check()["status"], "ERROR")

    def test_wrong_forecast_identity_features_and_publication_are_errors(self):
        original = json.dumps(self.forecast)
        for change in ("model", "features", "universe", "late", "preregistration"):
            with self.subTest(change=change):
                forecast = json.loads(original)
                if change == "model":
                    forecast["model_sha256"] = "different"
                elif change == "features":
                    forecast["metadata"]["shadow"]["feature_inputs"][0][FEATURES[0]] = 99.
                elif change == "universe":
                    forecast["predictions"].pop()
                else:
                    forecast["issued_at"] = "2026-10-19T13:30:00Z" if change == "late" else "2026-10-16T21:59:00Z"
                write_json(self.snapshot, forecast)
                self.assertEqual(self.check()["status"], "ERROR")

    def test_runtime_check_reports_shadow_failure_but_preflight_can_defer_it(self):
        from src.runtime_check import print_checks, runtime_checks

        (self.study / "model.joblib").write_bytes(b"corrupt")
        # Runtime checks use the default universe, which is also an explicit policy mismatch here.
        with self.clock(), patch("src.runtime_check.completed_session", return_value=pd.Timestamp("2026-10-16")):
            rows = runtime_checks(self.root)
            self.assertEqual([r["status"] for r in rows if r["check"] == "shadow study"], ["ERROR"])
            self.assertEqual(print_checks(self.root), 1)
            self.assertEqual(print_checks(self.root, include_shadow=False), 0)


class ShadowFailurePropagationTests(unittest.TestCase):
    def test_daily_update_publishes_before_shadow_failure_is_reported(self):
        import self_update_main as workflow

        calls = []
        def predict(**kwargs):
            calls.append("daily")
            return {"status": "RESEARCH_ONLY", "data_ready": True}
        def check():
            calls.append("shadow")
            return 1
        with patch("src.prediction.run_prediction", side_effect=predict), \
                patch("src.prediction_shadow_health.print_shadow_health", side_effect=check):
            with self.assertRaisesRegex(RuntimeError, "Daily forecasts completed"):
                workflow._run_prediction()
        self.assertEqual(calls, ["daily", "shadow"])
        with patch("src.runtime_check.print_checks", return_value=0) as checks:
            workflow._run_checks()
        checks.assert_called_once_with(include_shadow=False)

    def test_prediction_cli_returns_nonzero_for_shadow_failure_after_daily_run(self):
        import prediction_main

        with patch("sys.argv", ["prediction_main.py"]), \
                patch.object(prediction_main, "run_prediction", return_value={"data_ready": True}) as run, \
                patch.object(prediction_main, "print_shadow_health", return_value=1):
            self.assertEqual(prediction_main.main(), 2)
            run.assert_called_once()

    def test_web_update_exposes_shadow_failure_after_daily_prediction(self):
        from src.web_app import create_app

        with tempfile.TemporaryDirectory() as temp:
            client = create_app(Path(temp)).test_client()
            with patch("src.prediction.run_prediction", return_value={"as_of": "2026-10-16",
                       "decision_context": {"action": "NO_QUALIFIED_SIGNAL"}}) as run, \
                    patch("src.prediction_shadow_health.shadow_health", return_value={"status": "ERROR", "detail": "frozen checksum mismatch"}):
                response = client.post("/predict")
            self.assertEqual(response.status_code, 302)
            run.assert_called_once()
            with client.session_transaction() as session:
                messages = session["_flashes"]
            self.assertTrue(any(category == "warning" and "frozen checksum mismatch" in message for category, message in messages))


if __name__ == "__main__":
    unittest.main()
