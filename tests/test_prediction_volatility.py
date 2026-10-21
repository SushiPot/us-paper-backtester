from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import requests

from src.prediction_data import PredictionConfig, write_json
from src.prediction_experiments import load_protocol
from src.prediction_volatility import (CboeHistoryStore, COMBINED_FEATURES, SOURCES,
                                       VOLATILITY_FEATURES, build_volatility_dataset,
                                       parse_history, volatility_factors)
from test_prediction import market_frames


def index_histories(calendar):
    return {name: pd.DataFrame({"close": 20 + np.arange(len(calendar)) / 100 + offset},
                              index=calendar) for offset, name in enumerate(SOURCES)}


def csv_history(name):
    column = "VVIX" if name == "VVIX" else "CLOSE"
    return f"DATE,{column}\n01/02/2024,20\n01/03/2024,21\n".encode()


class VolatilityDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = CboeHistoryStore(self.root)

    def cache(self, name, content=None):
        content = content or csv_history(name)
        checksum = hashlib.sha256(content).hexdigest()
        path = self.root / "objects" / name / f"{checksum}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        record = {"schema": 1, "name": name, "url": SOURCES[name], "sha256": checksum,
                  "fetched_at": pd.Timestamp.now("UTC").isoformat()}
        write_json(self.root / f"{name}.json", record)
        return path, record

    def test_vendor_layouts_and_invalid_histories(self):
        for name in SOURCES:
            frame = parse_history(csv_history(name), name)
            self.assertEqual(frame.index[0], pd.Timestamp("2024-01-02"))
            self.assertEqual(frame.close.tolist(), [20, 21])
        for bad in (b"DATE,CLOSE\n01/02/2024,NaN\n", b"DATE,CLOSE\n01/02/2024,0\n",
                    b"DATE,CLOSE\n01/03/2024,20\n01/02/2024,21\n",
                    b"DATE,CLOSE\n01/02/2024,20\n01/02/2024,21\n", b"DATE,OPEN\n01/02/2024,20\n"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_history(bad, "VIX")

    def test_fresh_cache_avoids_requests_and_corruption_is_detected(self):
        for name in SOURCES:
            self.cache(name)
        with patch("src.prediction_volatility.requests.Session") as session:
            frames, inventory = self.store.load(refresh=True)
            session.return_value.__enter__.return_value.get.assert_not_called()
            self.assertEqual(set(frames), set(SOURCES))
            self.assertEqual(len(inventory), 3)
        path, _ = self.cache("VIX")
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.store.read("VIX")

    def test_bad_pointer_and_future_fetch_time_are_rejected(self):
        _, record = self.cache("VIX")
        for field, value in (("url", "https://invalid.example"), ("sha256", "../../other"),
                             ("fetched_at", "2099-01-01T00:00:00Z"), ("fetched_at", "2024-01-01")):
            with self.subTest(field=field):
                write_json(self.root / "VIX.json", {**record, field: value})
                with self.assertRaises(ValueError):
                    self.store.read("VIX")

    def test_rate_limit_stops_remaining_indices_and_survives_restart(self):
        response = Mock(status_code=429, headers={"Retry-After": "1800"})
        response.raise_for_status.side_effect = requests.HTTPError("rate limited")
        with patch("src.prediction_volatility.requests.Session") as session:
            get = session.return_value.__enter__.return_value.get
            get.return_value = response
            with self.assertRaises(requests.HTTPError):
                self.store.load(refresh=True)
            self.assertEqual(get.call_count, 1)
            with self.assertRaisesRegex(RuntimeError, "requests paused"):
                CboeHistoryStore(self.root).load(refresh=True)
            self.assertEqual(get.call_count, 1)
        state = json.loads((self.root / "network_state.json").read_text())
        self.assertGreater((pd.Timestamp(state["until"]) - pd.Timestamp.now("UTC")).total_seconds(), 1700)

    def test_failed_refresh_keeps_previous_immutable_history_and_pointer(self):
        path, record = self.cache("VIX")
        record["fetched_at"] = (pd.Timestamp.now("UTC") - pd.Timedelta(days=2)).isoformat()
        write_json(self.root / "VIX.json", record)
        before = (self.root / "VIX.json").read_bytes()
        response = Mock(status_code=200, headers={}, content=b"not a CSV")
        response.raise_for_status.return_value = None
        with patch("src.prediction_volatility.requests.Session") as session:
            session.return_value.__enter__.return_value.get.return_value = response
            with self.assertRaises(ValueError):
                self.store.load(refresh=True)
        self.assertEqual((self.root / "VIX.json").read_bytes(), before)
        self.assertEqual(path.read_bytes(), csv_history("VIX"))

    def test_download_preserves_versions_and_checks_required_pacing(self):
        session = Mock()
        response = Mock(status_code=200, headers={}, content=csv_history("VIX"))
        response.raise_for_status.return_value = None
        session.get.return_value = response
        with patch("src.prediction_volatility.time.sleep") as sleep, \
                patch("src.prediction_volatility.time.monotonic", return_value=100.0):
            self.store._last_request = 99.5
            _, first = self.store._download(session, "VIX")
            sleep.assert_called_once_with(1.0)
        response.content = csv_history("VIX").replace(b",21", b",22")
        _, second = self.store._download(session, "VIX")
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(len(list((self.root / "objects/VIX").glob("*.csv"))), 2)
        frame, _ = self.store.read("VIX")
        self.assertEqual(frame.close.iloc[-1], 22)


class VolatilityFeatureTests(unittest.TestCase):
    def test_current_and_future_observations_cannot_change_current_features(self):
        calendar = pd.bdate_range("2020-01-02", periods=150)
        histories = index_histories(calendar)
        first = volatility_factors(histories, calendar)
        cutoff = calendar[100]
        for frame in histories.values():
            frame.loc[frame.index >= cutoff, "close"] *= 2
        second = volatility_factors(histories, calendar)
        pd.testing.assert_frame_equal(first.loc[first.date <= cutoff], second.loc[second.date <= cutoff])
        self.assertEqual(first.loc[cutoff, "volatility_source_date"], calendar[99])
        self.assertAlmostEqual(first.loc[cutoff, "vix_previous_close"], 20.99)

    def test_missing_previous_session_is_not_filled_or_compressed(self):
        calendar = pd.bdate_range("2020-01-02", periods=150)
        histories = index_histories(calendar)
        histories["VIX"] = histories["VIX"].drop(index=calendar[100])
        features = volatility_factors(histories, calendar)
        self.assertTrue(pd.isna(features.loc[calendar[101], "vix_previous_close"]))
        self.assertEqual(features.loc[calendar[102], "volatility_source_date"], calendar[101])
        self.assertTrue(pd.isna(features.loc[calendar[102], "vix_mean_60_ratio"]))

    def test_control_and_candidate_share_common_support_and_original_labels(self):
        frames = market_frames(200)
        for frame in frames.values():
            frame.index.name = "date"
        histories = index_histories(frames["SPY"].index)
        histories["VVIX"] = histories["VVIX"].iloc[30:]
        config = PredictionConfig(symbols=("AAA", "BBB"))
        data, coverage = build_volatility_dataset(frames, histories, config)
        self.assertEqual(len(COMBINED_FEATURES), 20)
        self.assertLess(coverage["common_rows"], coverage["core_rows"])
        self.assertTrue(np.isfinite(data[COMBINED_FEATURES]).all().all())
        self.assertTrue((data.volatility_source_date < data.date).all())
        self.assertEqual(set(data.groupby("date").symbol.nunique()), {2})
        row = data.iloc[0]
        expected = frames[row.symbol].loc[row.label_end, "open"] / frames[row.symbol].loc[row.entry_date, "open"] - 1
        self.assertAlmostEqual(row.gross_return, expected)

    def test_registered_protocol_rejects_mismatched_data_and_features(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "config/prediction_experiment_volatility_v2.json"
        protocol = load_protocol(path)
        self.assertEqual(protocol["data_inputs"], "cboe_volatility")
        with tempfile.TemporaryDirectory() as tmp:
            broken = deepcopy(protocol)
            broken["data_inputs"] = "ohlcv"
            temporary = Path(tmp) / "protocol.json"
            write_json(temporary, broken)
            with self.assertRaisesRegex(ValueError, "candidate"):
                load_protocol(temporary)


if __name__ == "__main__":
    unittest.main()
