"""Health checks must not mistake a retained report for the latest run."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.prediction_data import write_json
from src.runtime_check import print_checks, runtime_checks


class RuntimeReportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.directory = self.root / "prediction"
        self.cache = self.root / "cache"
        self.report = {"status": "RESEARCH_ONLY", "as_of": "2026-10-29", "data_ready": True,
                       "updated_at": "2026-10-30T02:00:00Z", "model_sha256": "model-a",
                       "current_data_fingerprint": "inputs-a", "trading_enabled": False}
        self.save(self.report)

    def save(self, state):
        write_json(self.directory / "report.json", self.report)
        write_json(self.directory / "status.json", state)

    def checks(self):
        with patch("src.runtime_check.completed_session", return_value=pd.Timestamp("2026-10-29")):
            return {row["check"]: row for row in runtime_checks(self.root, include_shadow=False, cache_dir=self.cache)}

    def test_matching_completed_run_is_healthy_and_read_only(self):
        before = {p: p.read_bytes() for p in self.directory.iterdir()}
        with patch("requests.Session", side_effect=AssertionError("No network")), \
                patch("joblib.load", side_effect=AssertionError("No model loading")):
            rows = self.checks()
        self.assertEqual(rows["daily bars"]["status"], "OK")
        self.assertEqual(rows["real trading"]["status"], "OK")
        self.assertEqual(before, {p: p.read_bytes() for p in self.directory.iterdir()})

    def test_failed_or_running_state_cannot_reuse_old_report_success(self):
        for status in ("RUNNING", "ERROR", "STALE_DATA"):
            with self.subTest(status=status):
                self.save({"status": status, "trading_enabled": False})
                row = self.checks()["daily bars"]
                self.assertEqual(row["status"], "WARN")
                self.assertIn(f"run_status={status}", row["detail"])
                # A warning still allows the normal update to recover.
                with patch("src.runtime_check.completed_session", return_value=pd.Timestamp("2026-10-29")):
                    self.assertEqual(print_checks(self.root, include_shadow=False, cache_dir=self.cache), 0)

    def test_active_cooldown_is_read_only_warning_with_reason_and_utc_deadline(self):
        path = self.cache / "network_state.json"
        write_json(path, {"until": "2099-11-05T19:05:26+08:00", "reason": "Yahoo HTTP 403; requests paused"})
        before = path.read_bytes()
        with patch("requests.Session", side_effect=AssertionError("No network")):
            row = self.checks()["network cooldown"]
            self.assertEqual(print_checks(self.root, include_shadow=False, cache_dir=self.cache), 0)
        self.assertEqual(row["status"], "WARN")
        self.assertIn("active until=2099-11-05T11:05:26+00:00", row["detail"])
        self.assertIn("Yahoo HTTP 403", row["detail"])
        self.assertIn("connectivity not tested", row["detail"])
        self.assertEqual(path.read_bytes(), before)

    def test_missing_or_expired_cooldown_does_not_claim_network_is_healthy(self):
        row = self.checks()["network cooldown"]
        self.assertEqual(row["status"], "OK")
        self.assertIn("no persisted cooldown; connectivity not tested", row["detail"])
        self.assertFalse(self.cache.exists())
        path = self.cache / "network_state.json"
        write_json(path, {"until": "2000-01-01T00:00:00Z", "reason": "Network unavailable"})
        before = path.read_bytes()
        row = self.checks()["network cooldown"]
        self.assertEqual(row["status"], "OK")
        self.assertIn("expired until=", row["detail"])
        self.assertIn("connectivity not tested", row["detail"])
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_cooldown_metadata_warns_without_mutating_it(self):
        path = self.cache / "network_state.json"
        self.cache.mkdir()
        for content in ('not json', '[]', 'null', '{}',
                        '{"until": "NaT", "reason": "test"}',
                        '{"until": "2099-01-01", "reason": "test"}',
                        '{"until": 1, "reason": "test"}',
                        '{"until": "2099-01-01T00:00:00Z", "reason": " "}'):
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                row = self.checks()["network cooldown"]
                self.assertEqual(row["status"], "WARN")
                self.assertIn("cannot validate", row["detail"])
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_unreadable_cooldown_is_warning(self):
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path == self.cache / "network_state.json":
                raise PermissionError("unreadable")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            self.assertEqual(self.checks()["network cooldown"]["status"], "WARN")

    def test_run_identity_must_match_retained_report(self):
        for key in ("status", "as_of", "updated_at", "model_sha256", "current_data_fingerprint"):
            with self.subTest(key=key):
                self.save({**self.report, key: "RESEARCH_PASS" if key == "status" else "different"})
                self.assertEqual(self.checks()["daily bars"]["status"], "WARN")

    def test_target_session_is_not_presented_as_actual_data_date(self):
        self.report.update(status="STALE_DATA", data_ready=False)
        self.save(self.report)
        row = self.checks()["daily bars"]
        self.assertEqual(row["status"], "WARN")
        self.assertIn("report_session=2026-10-29", row["detail"])
        self.assertIn("data_ready=False", row["detail"])
        self.assertNotIn("data=2026-10-29", row["detail"])

    def test_missing_or_malformed_state_is_not_healthy(self):
        path = self.directory / "status.json"
        for value in (None, "not json", "[]", "null"):
            with self.subTest(value=value):
                if value is None:
                    path.unlink()
                else:
                    path.write_text(value, encoding="utf-8")
                self.assertEqual(self.checks()["daily bars"]["status"], "WARN")

    def test_ready_requires_boolean_true_and_both_safety_flags_are_checked(self):
        for value in (False, "false", 1, None):
            with self.subTest(data_ready=value):
                self.save({**self.report, "data_ready": value})
                self.assertEqual(self.checks()["daily bars"]["status"], "WARN")
        for which in ("state", "report"):
            with self.subTest(unsafe=which):
                state = dict(self.report)
                if which == "state":
                    state["trading_enabled"] = True
                else:
                    self.report["trading_enabled"] = True
                self.save(state)
                self.assertEqual(self.checks()["real trading"]["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
