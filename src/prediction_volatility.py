"""Verified public Cboe histories and conservative prior-session research factors."""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd
import requests

from .prediction_data import file_hash, write_json
from .prediction_features import FEATURES, build_dataset


SOURCES = {name: f"https://cdn-api.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv"
           for name in ("VIX", "VVIX", "VIX9D")}
VOLATILITY_FEATURES = ["vix_previous_close", "vvix_previous_close", "vix9d_previous_close",
                       "vix9d_vix_ratio", "vix_change_5", "vix_change_20",
                       "vix_mean_60_ratio", "vvix_mean_60_ratio"]
COMBINED_FEATURES = [*FEATURES, *VOLATILITY_FEATURES]


def parse_history(content: bytes, name: str) -> pd.DataFrame:
    if name not in SOURCES:
        raise ValueError("Unknown Cboe index")
    raw = pd.read_csv(BytesIO(content))
    value_column = "VVIX" if name == "VVIX" else "CLOSE"
    if "DATE" not in raw or value_column not in raw:
        raise ValueError(f"{name}: missing date/close columns")
    dates = pd.to_datetime(raw["DATE"], format="%m/%d/%Y", errors="raise")
    values = pd.to_numeric(raw[value_column], errors="raise").to_numpy(dtype=float)
    if (raw.empty or dates.isna().any() or dates.duplicated().any()
            or not dates.is_monotonic_increasing or not np.isfinite(values).all() or (values <= 0).any()):
        raise ValueError(f"{name}: invalid or unordered index history")
    return pd.DataFrame({"close": values}, index=pd.DatetimeIndex(dates, name="date"))


class CboeHistoryStore:
    def __init__(self, directory=Path("data_cache/cboe"), request_interval=1.5):
        self.directory = Path(directory)
        self.request_interval = max(1.0, float(request_interval))
        self._last_request = 0.0

    def read(self, name):
        if name not in SOURCES:
            raise ValueError("Unknown Cboe index")
        record = json.loads((self.directory / f"{name}.json").read_text(encoding="utf-8"))
        checksum = record.get("sha256", "")
        if (record.get("schema") != 1 or record.get("name") != name or record.get("url") != SOURCES[name]
                or not isinstance(checksum, str) or re.fullmatch(r"[a-f0-9]{64}", checksum) is None):
            raise ValueError(f"{name}: unverified history metadata")
        path = self.directory / "objects" / name / f"{checksum}.csv"
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != checksum:
            raise ValueError(f"{name}: history checksum mismatch")
        fetched = pd.Timestamp(record["fetched_at"])
        if pd.isna(fetched) or fetched.tzinfo is None or fetched > pd.Timestamp.now("UTC") + pd.Timedelta(minutes=5):
            raise ValueError(f"{name}: invalid fetch time")
        return parse_history(content, name), record

    def _check_cooldown(self):
        path = self.directory / "network_state.json"
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            until = pd.Timestamp(record["until"])
            if pd.isna(until) or until.tzinfo is None:
                raise ValueError("Invalid Cboe cooldown metadata")
            if until > pd.Timestamp.now("UTC"):
                raise RuntimeError(f"Cboe requests paused until {until.isoformat()}: {record['reason']}")

    def _pause(self, reason, seconds):
        write_json(self.directory / "network_state.json", {
            "reason": reason, "until": (pd.Timestamp.now("UTC") + pd.Timedelta(seconds=seconds)).isoformat()})

    def _download(self, session, name):
        self._check_cooldown()
        time.sleep(max(0.0, self.request_interval - (time.monotonic() - self._last_request)))
        try:
            response = session.get(SOURCES[name], timeout=30,
                                   headers={"User-Agent": "us-paper-backtester/1.0 (+https://github.com/SushiPot/us-paper-backtester)"})
            if response.status_code in (401, 403, 429) or response.status_code >= 500:
                seconds = 3600 if response.status_code in (401, 403) else 900
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            delay = (pd.Timestamp(retry_after) - pd.Timestamp.now("UTC")).total_seconds()
                        except (ValueError, TypeError):
                            delay = 0
                    if np.isfinite(delay):
                        seconds = max(seconds, delay)
                self._pause(f"HTTP {response.status_code}", seconds)
            response.raise_for_status()
            content = response.content
            if len(content) > 5_000_000:
                raise ValueError("Unexpectedly large Cboe history")
            frame = parse_history(content, name)
            checksum = hashlib.sha256(content).hexdigest()
            path = self.directory / "objects" / name / f"{checksum}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if file_hash(path) != checksum:
                    raise ValueError("Existing immutable history is corrupt")
            else:
                temporary = path.with_suffix(".csv.tmp")
                temporary.write_bytes(content)
                temporary.replace(path)
            record = {"schema": 1, "name": name, "url": SOURCES[name], "sha256": checksum,
                      "fetched_at": pd.Timestamp.now("UTC").isoformat(), "rows": len(frame),
                      "first_date": str(frame.index.min().date()), "last_date": str(frame.index.max().date())}
            write_json(self.directory / f"{name}.json", record)
            return frame, record
        except (requests.ConnectionError, requests.Timeout):
            self._pause("Network unavailable", 300)
            raise
        finally:
            self._last_request = time.monotonic()

    def load(self, *, refresh=False):
        frames, inventory = {}, []
        # Reuse the same OS lock as research runs; different output directories cannot burst this provider.
        from .prediction import prediction_lock

        with prediction_lock(self.directory), requests.Session() as session:
            for name in SOURCES:
                try:
                    frame, record = self.read(name)
                except (OSError, ValueError, KeyError, TypeError):
                    if not refresh:
                        raise
                    frame, record = None, {}
                age = (pd.Timestamp.now("UTC") - pd.Timestamp(record["fetched_at"])).total_seconds() if record else float("inf")
                if refresh and age >= 86400:
                    print(f"[CBOE] Fetching {name} history", flush=True)
                    frame, record = self._download(session, name)
                frames[name] = frame
                inventory.append(record)
        return frames, inventory


def volatility_factors(histories, calendar):
    if set(histories) != set(SOURCES):
        raise ValueError("All registered Cboe inputs are required")
    calendar = pd.DatetimeIndex(calendar)
    if calendar.has_duplicates or not calendar.is_monotonic_increasing or calendar.hasnans:
        raise ValueError("Invalid feature calendar")
    values = pd.DataFrame({name: histories[name]["close"].reindex(calendar) for name in SOURCES}, index=calendar)
    factors = pd.DataFrame(index=calendar)
    factors["vix_previous_close"] = values.VIX
    factors["vvix_previous_close"] = values.VVIX
    factors["vix9d_previous_close"] = values.VIX9D
    factors["vix9d_vix_ratio"] = values.VIX9D / values.VIX - 1
    factors["vix_change_5"] = values.VIX.pct_change(5, fill_method=None)
    factors["vix_change_20"] = values.VIX.pct_change(20, fill_method=None)
    factors["vix_mean_60_ratio"] = values.VIX / values.VIX.rolling(60).mean() - 1
    factors["vvix_mean_60_ratio"] = values.VVIX / values.VVIX.rolling(60).mean() - 1
    # Shift on the complete stock calendar, never on the surviving Cboe rows and never forward-fill.
    factors = factors.shift(1).replace([np.inf, -np.inf], np.nan)
    factors["volatility_source_date"] = pd.Series(calendar, index=calendar).shift(1)
    factors["date"] = calendar
    return factors


def build_volatility_dataset(frames, histories, config):
    core = build_dataset(frames, config)
    factors = volatility_factors(histories, frames["SPY"].index).reset_index(drop=True)
    combined = core.merge(factors, on="date", validate="many_to_one").dropna(subset=COMBINED_FEATURES)
    if not (combined.volatility_source_date < combined.date).all():
        raise ValueError("Volatility features must precede the signal session")
    return combined.sort_values(["date", "symbol"]).reset_index(drop=True), {
        "core_rows": len(core), "common_rows": len(combined), "feature_rows_excluded": len(core) - len(combined),
        "core_features": len(FEATURES), "combined_features": len(COMBINED_FEATURES),
        "common_first_date": str(combined.date.min().date()) if len(combined) else None,
        "alignment": "Previous stock trading session only; missing index rows are not filled"}
