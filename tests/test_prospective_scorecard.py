import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.prediction_data import PredictionConfig, file_hash
from src.prediction_prospective import _metrics, evaluate_prospective


class ProspectiveScorecardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "issued").mkdir()
        (self.root / "model.joblib").write_bytes(b"current-model")
        self.sha = file_hash(self.root / "model.joblib")
        self.config = PredictionConfig(symbols=("AAA", "BBB"), top_k=2, output_dir=self.root)
        self.data = pd.DataFrame({"date": pd.to_datetime(["2026-01-02", "2026-01-02", "2026-10-01"]),
                                  "symbol": ["AAA", "BBB", "SPY"],
                                  "entry_date": pd.to_datetime(["2026-01-05", "2026-01-05", None]),
                                  "label_end": pd.to_datetime(["2026-01-12", "2026-01-12", None]),
                                  "target": [1., 0., np.nan], "gross_return": [.02, -.01, np.nan]})

    def snapshot(self, day="2026-01-02", **overrides):
        value = {"as_of": day, "issued_at": f"{day}T22:00:00+00:00", "horizon": 5, "cost_bps": 20.0,
                 "model_sha256": self.sha, "metadata": {"threshold": .55, "config": {"symbols": ["AAA", "BBB"], "top_k": 1}},
                 "predictions": [{"symbol": "AAA", "probability": .8}, {"symbol": "BBB", "probability": .4}]}
        value.update(overrides)
        path = self.root / "issued" / f"{day}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_accuracy_baselines_and_ranked_signals_are_distinct(self):
        path = self.snapshot()
        original = path.read_bytes()
        report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["eligible_rows"], 2)
        self.assertEqual(report["classification_accuracy"], 1.0)
        self.assertEqual(report["always_positive_accuracy"], .5)
        score = pd.read_csv(self.root / "prospective_scorecard.csv").iloc[0]
        self.assertEqual(score.signal_count, 1)
        self.assertEqual(score.ranked_signal_count, 1)
        self.assertEqual(score.ranked_signal_hit_rate, 1.0)
        self.assertEqual(score.nonoverlap_windows, 1)
        self.assertAlmostEqual(score.brier, .1)
        self.assertEqual(score.half_probability_brier, .25)
        self.assertEqual(report["evidence_status"], "INSUFFICIENT_PROSPECTIVE_DATA")
        self.assertNotIn("trade_win_rate", report["current_model"])
        self.assertEqual(path.read_bytes(), original)

    def test_partial_outcomes_do_not_select_only_the_survivor(self):
        self.snapshot()
        incomplete = self.data.loc[self.data.symbol != "BBB"]
        report = evaluate_prospective(incomplete, self.config)
        self.assertEqual(report["mature_rows"], 1)
        self.assertEqual(report["eligible_rows"], 0)
        self.assertIsNone(report["classification_accuracy"])
        self.assertEqual(report["status_counts"], {"INCOMPLETE_OUTCOMES": 1})
        outcomes = pd.read_csv(self.root / "issued_outcomes.csv")
        self.assertFalse(outcomes.eligible_prospective.any())

    def test_waiting_outcomes_are_na_not_zero_accuracy(self):
        self.snapshot()
        data = self.data.copy()
        data.loc[data.symbol.isin(["AAA", "BBB"]), ["target", "gross_return"]] = np.nan
        report = evaluate_prospective(data, self.config)
        self.assertEqual(report["status_counts"], {"WAITING_OUTCOMES": 1})
        self.assertIsNone(report["brier"])
        self.assertIsNone(report["current_model"]["classification_accuracy"])
        self.assertFalse(report["trading_enabled"])

    def test_publication_window_excludes_early_late_and_future_issues(self):
        for issued, status in (("2026-01-02T21:29:59Z", "BEFORE_DATA_AVAILABLE"),
                               ("2026-01-05T14:30:00Z", "LATE_ISSUE"),
                               ("2099-01-01T00:00:00Z", "FUTURE_ISSUE_TIME")):
            with self.subTest(issued=issued):
                self.snapshot(issued_at=issued)
                report = evaluate_prospective(self.data, self.config)
                self.assertEqual(report["eligible_rows"], 0)
                self.assertEqual(report["status_counts"], {status: 1})
        self.snapshot(issued_at="2026-01-02T21:30:00Z")
        self.assertEqual(evaluate_prospective(self.data, self.config)["eligible_rows"], 2)

    def test_invalid_archive_does_not_hide_valid_forecasts(self):
        self.snapshot()
        (self.root / "issued/2026-01-03.json").write_text("[]")
        report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["issued_days"], 2)
        self.assertEqual(report["eligible_rows"], 2)
        self.assertEqual(report["status_counts"]["INVALID"], 1)

    def test_invalid_probabilities_duplicates_and_missing_symbols_are_rejected(self):
        for predictions in (({"symbol": "AAA", "probability": float("nan")}, {"symbol": "BBB", "probability": .4}),
                            ({"symbol": "AAA", "probability": .8}, {"symbol": "AAA", "probability": .4}),
                            ({"symbol": "AAA", "probability": .8},),
                            ({"symbol": "AAA", "probability": 1.1}, {"symbol": "BBB", "probability": .4})):
            with self.subTest(predictions=predictions):
                self.snapshot(predictions=predictions)
                report = evaluate_prospective(self.data, self.config)
                self.assertEqual(report["status_counts"], {"INVALID": 1})
                self.assertEqual(report["eligible_rows"], 0)

    def test_archived_threshold_and_position_count_override_current_settings(self):
        self.snapshot(predictions=[{"symbol": "AAA", "probability": .8}, {"symbol": "BBB", "probability": .7}],
                      metadata={"threshold": .75, "config": {"symbols": ["AAA", "BBB"], "top_k": 1}})
        evaluate_prospective(self.data, self.config)
        score = pd.read_csv(self.root / "prospective_scorecard.csv").iloc[0]
        self.assertEqual(score.threshold, .75)
        self.assertEqual(score.top_k, 1)
        self.assertEqual(score.signal_count, 1)
        self.assertEqual(score.ranked_signal_count, 1)

    def test_model_versions_are_not_combined_into_current_model_evidence(self):
        self.snapshot()
        second = self.data.loc[self.data.symbol != "SPY"].copy()
        second["date"] = pd.Timestamp("2026-01-05")
        second["entry_date"] = pd.Timestamp("2026-01-06")
        second["label_end"] = pd.Timestamp("2026-01-13")
        data = pd.concat([self.data, second], ignore_index=True)
        self.snapshot(day="2026-01-05", model_sha256="older-model")
        report = evaluate_prospective(data, self.config)
        self.assertEqual(report["eligible_rows"], 4)
        self.assertEqual(report["current_model"]["rows"], 2)
        self.assertEqual(report["policy_count"], 2)
        self.assertEqual(len(pd.read_csv(self.root / "prospective_scorecard.csv")), 2)

    def test_archived_policy_with_unknown_threshold_is_not_given_new_signals(self):
        self.snapshot(metadata={})
        report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["eligible_rows"], 2)
        self.assertEqual(report["current_model"]["signal_count"], 0)
        self.assertIsNone(report["current_model"]["signal_hit_rate"])

    def test_incompatible_horizon_or_cost_is_not_evaluated_with_current_labels(self):
        for change in ({"horizon": 10}, {"cost_bps": 40}):
            self.snapshot(**change)
            result = evaluate_prospective(self.data, self.config)
            self.assertEqual(result["status_counts"], {"INCOMPATIBLE_POLICY": 1})
            self.assertEqual(result["eligible_rows"], 0)

    def test_invalid_realized_target_and_entry_date_are_not_scored(self):
        self.snapshot()
        for column, value in (("target", 0), ("entry_date", pd.Timestamp("2026-01-06")),
                              ("label_end", pd.Timestamp("2026-01-13"))):
            data = self.data.copy()
            data.loc[data.symbol == "AAA", column] = value
            with self.subTest(column=column):
                result = evaluate_prospective(data, self.config)
                self.assertEqual(result["eligible_rows"], 0)
                self.assertEqual(result["status_counts"], {"INVALID": 1})

    def test_wrong_exchange_session_horizon_is_not_a_mature_valid_forecast(self):
        self.snapshot()
        data = self.data.copy()
        data.loc[data.symbol != "SPY", "label_end"] = pd.Timestamp("2026-01-13")
        result = evaluate_prospective(data, self.config)
        self.assertEqual(result["eligible_rows"], 0)
        self.assertEqual(result["status_counts"], {"INVALID": 1})

    def test_overlapping_cohorts_do_not_count_as_independent_windows(self):
        dates = pd.bdate_range("2025-01-02", periods=60)
        frame = pd.DataFrame({"date": dates, "entry_date": dates + pd.Timedelta(days=1),
                              "label_end": dates + pd.Timedelta(days=8), "probability": .8,
                              "target": 1, "threshold": .55, "rank_selected": True, "policy_key": "one"})
        metrics = _metrics(frame)
        self.assertEqual(metrics["ranked_signal_count"], 60)
        self.assertLess(metrics["ranked_signal_windows"], 26)
        self.assertEqual(metrics["evidence_status"], "INSUFFICIENT_PROSPECTIVE_DATA")
        separated = pd.date_range("2020-01-02", periods=60, freq="14D")
        frame["date"] = separated
        frame["entry_date"] = separated + pd.Timedelta(days=1)
        frame["label_end"] = separated + pd.Timedelta(days=8)
        self.assertEqual(_metrics(frame)["evidence_status"], "MONITORING_ONLY")
        frame.loc[frame.index >= 30, "policy_key"] = "another-policy"
        self.assertEqual(_metrics(frame)["evidence_status"], "MIXED_POLICIES")

    def test_naive_issue_time_non_session_and_filename_mismatch_are_invalid(self):
        self.snapshot(issued_at="2026-01-02T22:00:00")
        self.assertEqual(evaluate_prospective(self.data, self.config)["status_counts"], {"INVALID": 1})
        self.snapshot(day="2026-01-03")
        self.assertEqual(evaluate_prospective(self.data, self.config)["status_counts"], {"INVALID": 2})
        self.snapshot(day="2026-01-03", as_of="2026-01-02")
        self.assertEqual(evaluate_prospective(self.data, self.config)["status_counts"], {"INVALID": 2})

    def test_future_training_or_selection_cutoff_is_rejected(self):
        self.snapshot(metadata={"threshold": .55, "training_last_label_date": "2026-02-01"})
        self.assertEqual(evaluate_prospective(self.data, self.config)["status_counts"], {"INVALID": 1})

    def test_audit_checks_model_hash_before_loading_joblib(self):
        from src.prediction_audit import run_audit

        settings = {key: str(value) if isinstance(value, Path) else value for key, value in vars(self.config).items()}
        (self.root / "report.json").write_text(json.dumps({"metadata": {"config": settings}, "model_sha256": "wrong"}))
        with patch("src.prediction_audit.joblib.load") as deserialize:
            with self.assertRaisesRegex(ValueError, "checksum"):
                run_audit(self.root)
        deserialize.assert_not_called()

    def test_empty_dashboard_evidence_is_unverified_not_zero_accuracy(self):
        from src.web_app import create_app

        prediction_dir = self.root / "prediction"
        prediction_dir.mkdir()
        (prediction_dir / "report.json").write_text(json.dumps({"prospective": {"evidence_status": "INSUFFICIENT_PROSPECTIVE_DATA"}}))
        response = create_app(self.root).test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Not Yet Verified", response.data)
        self.assertIn(b"Forward Evidence By Model", response.data)
        self.assertNotIn(b"0.00%", response.data)

    def test_first_complete_outcomes_are_frozen_and_reused_without_writes(self):
        forecast = self.snapshot()
        original_forecast = forecast.read_bytes()
        first = evaluate_prospective(self.data, self.config)
        path = self.root / "observed_outcomes/2026-01-02.json"
        saved = path.read_bytes()
        stamp = path.stat().st_mtime_ns
        second = evaluate_prospective(self.data.iloc[::-1], self.config)
        self.assertEqual(first["classification_accuracy"], second["classification_accuracy"])
        self.assertEqual(second["outcome_review_days"], 0)
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual(path.stat().st_mtime_ns, stamp)
        self.assertEqual(forecast.read_bytes(), original_forecast)
        self.assertEqual(pd.read_csv(self.root / "prospective_inventory.csv").outcome_check.iloc[0], "SAME")

    def test_later_revisions_do_not_rewrite_scores_or_create_duplicate_events(self):
        self.snapshot()
        first = evaluate_prospective(self.data, self.config)
        path = self.root / "observed_outcomes/2026-01-02.json"
        saved = path.read_bytes()
        revised = self.data.copy()
        revised.loc[revised.symbol == "BBB", ["target", "gross_return"]] = [1., .03]
        for _ in range(2):
            report = evaluate_prospective(revised, self.config)
            self.assertEqual(report["classification_accuracy"], first["classification_accuracy"])
            self.assertEqual(report["eligible_rows"], 2)
            self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
            self.assertEqual(report["outcome_review_days"], 1)
        self.assertEqual(path.read_bytes(), saved)
        events = list((self.root / "outcome_revisions/2026-01-02").glob("*.json"))
        self.assertEqual(len(events), 1)
        event = json.loads(events[0].read_text())
        self.assertEqual(event["check"], "REVISED")
        self.assertEqual(event["current_outcomes"][1]["target"], 1.)
        report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
        self.assertEqual(len(list(events[0].parent.glob("*.json"))), 1)

    def test_missing_losing_outcomes_cannot_remove_a_frozen_cohort(self):
        self.snapshot(predictions=[{"symbol": "AAA", "probability": .8}, {"symbol": "BBB", "probability": .9}])
        first = evaluate_prospective(self.data, self.config)
        report = evaluate_prospective(self.data.loc[self.data.symbol != "BBB"], self.config)
        self.assertEqual(report["eligible_rows"], 2)
        self.assertEqual(report["classification_accuracy"], first["classification_accuracy"])
        self.assertEqual(report["current_model"]["ranked_signal_hit_rate"], 0.)
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
        inventory = pd.read_csv(self.root / "prospective_inventory.csv")
        self.assertEqual(inventory.outcome_check.iloc[0], "UNAVAILABLE")

    def test_invalid_current_data_keeps_first_outcomes_visible_with_review_flag(self):
        self.snapshot()
        evaluate_prospective(self.data, self.config)
        for value in (float("inf"), -.5):
            revised = self.data.copy()
            revised.loc[revised.symbol == "AAA", "gross_return"] = value
            report = evaluate_prospective(revised, self.config)
            self.assertEqual(report["eligible_rows"], 2)
            self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
            self.assertEqual(pd.read_csv(self.root / "prospective_inventory.csv").outcome_check.iloc[0], "INVALID_CURRENT")

    def test_corrupt_archive_is_not_silently_recreated(self):
        self.snapshot()
        evaluate_prospective(self.data, self.config)
        path = self.root / "observed_outcomes/2026-01-02.json"
        path.write_text("{}")
        report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["status_counts"], {"INVALID": 1})
        self.assertEqual(report["eligible_rows"], 0)
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
        self.assertEqual(path.read_text(), "{}")

    def test_changed_forecast_cannot_rebind_original_outcome_archive(self):
        self.snapshot()
        evaluate_prospective(self.data, self.config)
        path = self.root / "observed_outcomes/2026-01-02.json"
        saved = path.read_bytes()
        self.snapshot(predictions=[{"symbol": "AAA", "probability": .1}, {"symbol": "BBB", "probability": .9}])
        report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["status_counts"], {"INVALID": 1})
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
        self.assertEqual(path.read_bytes(), saved)

    def test_late_and_partial_cohorts_do_not_freeze_outcomes(self):
        self.snapshot(issued_at="2026-01-05T14:30:00Z")
        evaluate_prospective(self.data, self.config)
        self.assertFalse((self.root / "observed_outcomes/2026-01-02.json").exists())
        self.snapshot()
        evaluate_prospective(self.data.loc[self.data.symbol != "BBB"], self.config)
        self.assertFalse((self.root / "observed_outcomes/2026-01-02.json").exists())
        evaluate_prospective(self.data, self.config)
        self.assertTrue((self.root / "observed_outcomes/2026-01-02.json").exists())

    def test_corrupt_revision_record_does_not_clear_review(self):
        self.snapshot()
        evaluate_prospective(self.data, self.config)
        revised = self.data.copy()
        revised.loc[revised.symbol == "AAA", "gross_return"] = .03
        evaluate_prospective(revised, self.config)
        event = next((self.root / "outcome_revisions/2026-01-02").glob("*.json"))
        event.write_text("[]")
        report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
        self.assertEqual(event.read_text(), "[]")

    def test_future_outcomes_cannot_be_frozen_even_with_future_dataset_dates(self):
        self.snapshot()
        with patch("src.prediction_prospective.completed_session", return_value=pd.Timestamp("2026-01-09")):
            report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["eligible_rows"], 0)
        self.assertFalse((self.root / "observed_outcomes/2026-01-02.json").exists())

    def test_deleted_issued_forecast_leaves_visible_orphan_warning(self):
        path = self.snapshot()
        evaluate_prospective(self.data, self.config)
        path.unlink()
        report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["status_counts"], {"ORPHANED_OUTCOME_ARCHIVE": 1})
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
        self.assertTrue((self.root / "observed_outcomes/2026-01-02.json").exists())

    def test_dashboard_marks_outcome_data_review_explicitly(self):
        from src.web_app import create_app

        prediction_dir = self.root / "prediction"
        prediction_dir.mkdir()
        (prediction_dir / "report.json").write_text(json.dumps({"prospective": {"evidence_status": "DATA_REVIEW_REQUIRED"}}))
        response = create_app(self.root).test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Data Review Required", response.data)

    def test_archive_write_failure_requires_review_and_preserves_forecast(self):
        path = self.snapshot()
        before = path.read_bytes()
        with patch("src.prediction_outcome_archive.write_json", side_effect=OSError("disk unavailable")):
            report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
        self.assertEqual(report["eligible_rows"], 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / "observed_outcomes/2026-01-02.json").exists())

    def test_concurrent_archive_writer_cannot_overwrite_evidence(self):
        from src.prediction import prediction_lock

        self.snapshot()
        with prediction_lock(self.root / "observed_outcomes"):
            report = evaluate_prospective(self.data, self.config)
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")
        self.assertEqual(report["eligible_rows"], 0)
        self.assertEqual(evaluate_prospective(self.data, self.config)["eligible_rows"], 2)

    def test_empty_current_dataset_does_not_erase_archived_scores(self):
        self.snapshot()
        evaluate_prospective(self.data, self.config)
        report = evaluate_prospective(self.data.iloc[:0], self.config)
        self.assertEqual(report["eligible_rows"], 2)
        self.assertEqual(report["evidence_status"], "DATA_REVIEW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
