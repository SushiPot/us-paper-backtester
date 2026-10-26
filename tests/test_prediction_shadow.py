from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier

from src.prediction import _config_dict, prediction_lock
from src.prediction_data import PredictionConfig, file_hash, write_json
from src.prediction_features import FEATURES
from src.prediction_shadow import STUDY, register_shadow, run_registered_shadow


@contextmanager
def clock(value):
    timestamp = pd.Timestamp
    now = timestamp(value)
    with patch("pandas.Timestamp", side_effect=timestamp) as stamp, \
            patch("src.prediction.now_new_york", return_value=now.tz_convert("America/New_York").to_pydatetime()), \
            patch("src.prediction_shadow.now_new_york", return_value=now.tz_convert("America/New_York").to_pydatetime()), \
            patch("src.market_calendar.now_new_york", return_value=now.tz_convert("America/New_York").to_pydatetime()):
        stamp.now.return_value = now
        stamp.min = timestamp.min
        yield


class FrozenShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = PredictionConfig(symbols=("AAA", "BBB"), top_k=2, output_dir=self.root)
        self.shadow = self.root / "shadow" / STUDY
        self.write_model("anchor")
        self.inventory = pd.DataFrame({"symbol": ["AAA", "BBB"], "status": "CURRENT", "sha256": ["a", "b"]})
        self.data = self.rows("2026-10-16")

    def rows(self, day):
        frame = pd.DataFrame(0., index=range(2), columns=FEATURES)
        frame["date"], frame["symbol"] = pd.Timestamp(day), ["AAA", "BBB"]
        frame["entry_date"] = pd.NaT
        frame["label_end"] = pd.NaT
        frame["target"], frame["gross_return"] = np.nan, np.nan
        return frame

    def write_model(self, key):
        strategy = "prior" if key == "anchor" else "most_frequent"
        model = DummyClassifier(strategy=strategy).fit(pd.DataFrame(0., index=range(4), columns=FEATURES), [0, 1, 1, 1])
        model_metadata = {"features": FEATURES, "config": _config_dict(self.config), "selected_model": "dummy",
                          "threshold": .55, "training_key": key, "training_last_label_date": "2021-12-31"}
        joblib.dump({"model": model, "metadata": model_metadata}, self.root / "model.joblib")
        write_json(self.root / "model_manifest.json", {"model_sha256": file_hash(self.root / "model.joblib"),
                   "input_key": key, "prior": .5, "trained_at": "2026-10-15T21:00:00+00:00"})

    def register(self):
        with clock("2026-10-16T22:00:00Z"):
            return register_shadow(self.config)

    def observe(self, data=None, day="2026-10-16", issued_at="2026-10-16T22:01:00Z", inventory=None):
        with clock(issued_at):
            return run_registered_shadow(self.data if data is None else data,
                                         self.inventory if inventory is None else inventory,
                                         self.config, pd.Timestamp(day))

    def test_registration_is_idempotent_verified_and_does_not_fit_or_download(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch("src.prediction.fit_select", side_effect=AssertionError("No fitting")), \
                patch("src.prediction_data.requests.Session", side_effect=AssertionError("No network")):
            record = self.register()
            frozen = (self.shadow / "registration.json").read_bytes()
            self.write_model("new-daily-version")
            self.assertEqual(self.register(), record)
            self.assertEqual((self.shadow / "registration.json").read_bytes(), frozen)
            self.assertEqual((self.shadow / "model.joblib").read_bytes(), before["model.joblib"])
            result = self.observe()
        self.assertEqual(result["status"], "OBSERVING")
        self.assertFalse(result["minimum_observation_complete"] or result["policy_changed"] or result["trading_enabled"])
        forecast = json.loads((self.shadow / "issued/2026-10-16.json").read_text())
        self.assertTrue(all(row["probability"] == .75 for row in forecast["predictions"]))
        inputs = pd.DataFrame(forecast["metadata"]["shadow"]["feature_inputs"])
        np.testing.assert_array_equal(joblib.load(self.shadow / "model.joblib")["model"].predict_proba(inputs[FEATURES])[:, 1], [.75, .75])
        self.assertEqual(forecast["metadata"]["shadow"]["sources"], self.inventory.to_dict("records"))
        self.assertFalse((self.root / "issued").exists())

    def test_same_day_rerun_keeps_first_features_probabilities_and_timestamp(self):
        self.register()
        self.observe()
        path = self.shadow / "issued/2026-10-16.json"
        first = path.read_bytes()
        self.data[FEATURES[0]] = 20.
        self.observe(issued_at="2026-10-16T23:00:00Z")
        self.assertEqual(path.read_bytes(), first)

    def test_stale_early_late_and_preregistration_dates_do_not_issue_forecasts(self):
        self.register()
        stale = self.inventory.assign(status="STALE")
        self.assertEqual(self.observe(inventory=stale)["status"], "STALE_DATA")
        for issue_time in ("2026-10-16T21:29:00Z", "2026-10-19T13:30:00Z"):
            self.assertFalse(self.observe(issued_at=issue_time)["timely"])
        self.assertFalse(self.observe(self.rows("2026-10-15"), "2026-10-15")["timely"])
        self.assertFalse((self.shadow / "issued").exists())

    def test_frozen_artifact_corruption_blocks_before_deserialization_and_is_reported(self):
        self.register()
        (self.shadow / "model.joblib").write_bytes(b"corrupt")
        with patch("src.prediction_shadow.joblib.load", side_effect=AssertionError("Must verify before loading")) as load:
            result = self.observe()
            load.assert_not_called()
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(json.loads((self.shadow / "status.json").read_text())["status"], "ERROR")
        self.assertFalse((self.shadow / "issued").exists())
        with self.assertRaises(ValueError):
            self.register()

    def test_publication_opens_exactly_at_close_plus_thirty_minutes(self):
        with clock("2026-10-16T19:00:00Z"):
            register_shadow(self.config)
        self.assertFalse(self.observe(issued_at="2026-10-16T20:29:59Z")["timely"])
        self.assertFalse((self.shadow / "issued").exists())
        self.assertTrue(self.observe(issued_at="2026-10-16T20:30:00Z")["timely"])
        self.assertTrue((self.shadow / "issued/2026-10-16.json").exists())

    def test_registration_rejects_unverified_or_conflicting_partial_artifacts(self):
        original = (self.root / "model.joblib").read_bytes()
        (self.root / "model.joblib").write_bytes(b"broken")
        with patch("src.prediction_shadow.joblib.load", side_effect=AssertionError("Must verify first")) as load:
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                self.register()
            load.assert_not_called()
        (self.root / "model.joblib").write_bytes(original)
        (self.shadow / "model.joblib").write_bytes(b"partial")
        self.assertEqual(self.observe()["status"], "INCOMPLETE_REGISTRATION")
        with self.assertRaisesRegex(ValueError, "Refusing to replace"):
            self.register()
        self.assertFalse((self.shadow / "registration.json").exists())
        self.assertEqual((self.shadow / "model.joblib").read_bytes(), b"partial")

    def test_protocol_environment_and_policy_drift_do_not_replace_anchor(self):
        self.register()
        original = (self.shadow / "model.joblib").read_bytes()
        with patch("src.prediction_shadow._versions", return_value={"different": "environment"}):
            self.assertEqual(self.observe()["status"], "ERROR")
        with patch("src.prediction_shadow._sources", return_value={"different": "implementation"}):
            self.assertEqual(self.observe()["status"], "ERROR")
        self.config = replace(self.config, top_k=1)
        self.assertEqual(self.observe()["status"], "ERROR")
        self.assertEqual((self.shadow / "model.joblib").read_bytes(), original)

    def test_complete_outcomes_are_separate_and_vendor_revision_keeps_first_score(self):
        self.register()
        self.observe()
        realized = self.data.copy()
        realized["entry_date"], realized["label_end"] = pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-26")
        realized["target"], realized["gross_return"] = [1., 0.], [.02, -.01]
        current = self.rows("2026-10-26")
        data = pd.concat([realized, current], ignore_index=True)
        result = self.observe(data, "2026-10-26", "2026-10-26T22:00:00Z")
        self.assertEqual(result["prospective"]["eligible_dates"], 1)
        self.assertEqual(result["prospective"]["current_model"]["classification_accuracy"], .5)
        self.assertFalse(result["minimum_observation_complete"])
        archive = self.shadow / "observed_outcomes/2026-10-16.json"
        original = archive.read_bytes()
        data.loc[data.symbol.eq("BBB") & data.date.eq("2026-10-16"), ["target", "gross_return"]] = [1., .01]
        revised = self.observe(data, "2026-10-26", "2026-10-26T23:00:00Z")
        self.assertEqual(revised["status"], "DATA_REVIEW_REQUIRED")
        self.assertEqual(revised["prospective"]["current_model"]["classification_accuracy"], .5)
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse((self.root / "observed_outcomes").exists())

    def test_registration_and_observation_respect_process_lock(self):
        self.assertEqual(self.observe()["status"], "NOT_REGISTERED")
        self.register()
        with prediction_lock(self.shadow):
            self.assertEqual(self.observe()["status"], "ERROR")
            with self.assertRaises(OSError):
                self.register()


if __name__ == "__main__":
    unittest.main()
