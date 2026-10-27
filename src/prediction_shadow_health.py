"""Read-only operational checks; never alter a registered study or its evidence."""
from __future__ import annotations

from datetime import datetime, time
import json

import numpy as np
import pandas as pd

from .market_calendar import NEW_YORK_TZ, completed_session, get_us_market_session, next_session_open, now_new_york
from .prediction_data import PredictionConfig, file_hash
from .prediction_features import FEATURES
from .prediction_prospective import _snapshot
from .prediction_shadow import _digest, _protocol, _read_registration, _root, _settings, _sources, _versions


def shadow_health(config: PredictionConfig | None = None) -> dict:
    config = config or PredictionConfig()
    root = _root(config)
    row = {"check": "shadow study", "status": "OK", "detail": "", "missing_dates": [], "pending_dates": []}
    try:
        if not (root / "registration.json").exists():
            partial = root.exists() and any(path.name != ".run.lock" for path in root.iterdir())
            return {**row, "status": "ERROR" if partial else "SKIP",
                    "detail": "Missing registration for existing shadow artifacts" if partial else "not registered"}
        registration, checksum = _read_registration(root)
        if (registration["protocol"] != _protocol() or registration["settings"] != _settings(config)
                or registration["sources"] != _sources() or registration["versions"] != _versions()):
            raise ValueError("Frozen protocol, policy, implementation or environment changed")
        if set(registration["files"]) != {"model.joblib", "model_manifest.json"}:
            raise ValueError("Incomplete frozen artifact identities")
        for name, expected in registration["files"].items():
            if file_hash(root / name) != expected:
                raise ValueError(f"Frozen artifact checksum mismatch: {name}")
        model_hash = registration["files"]["model.joblib"]
        registered = pd.Timestamp(registration["registered_at"])
        first = pd.Timestamp(registration["first_signal_session"])
        now, expected_session = pd.Timestamp(now_new_york()), completed_session()
        if (registered.tzinfo is None or pd.isna(registered) or registered > now
                or pd.isna(first) or first.tzinfo is not None or first != first.normalize() or first > expected_session):
            raise ValueError("Invalid registration time or first session")
        report = json.loads((root / "status.json").read_text(encoding="utf-8"))
        if report["status"] != "OBSERVING":
            raise ValueError(f"Shadow is {report['status']}: {report.get('error', 'review required')}")
        if (report["registration_sha256"] != checksum or report["model_sha256"] != model_hash
                or report["trading_enabled"] is not False or report["policy_changed"] is not False):
            raise ValueError("Shadow report identity or safety flags disagree with registration")
        updated = pd.Timestamp(report["updated_at"])
        if (pd.isna(updated) or updated.tzinfo is None or updated < registered
                or updated > now + pd.Timedelta(minutes=5) or report["as_of"] != str(expected_session.date())):
            raise ValueError("Shadow report is stale or has an invalid timestamp")
        if report["prospective"]["outcome_review_days"]:
            raise ValueError("First-observed outcomes require review")

        valid_dates = set()
        for path in sorted((root / "issued").glob("*.json")):
            snapshot, _, policy = _snapshot(path, config)
            date, issued = policy["date"], policy["issued_at"]
            session = get_us_market_session(datetime.combine(date.date(), time(12), tzinfo=NEW_YORK_TZ))
            if (date < first or date > expected_session or session.market_close is None
                    or issued < registered or issued < pd.Timestamp(session.market_close) + pd.Timedelta(minutes=30)
                    or issued >= pd.Timestamp(next_session_open(date)) or issued > now + pd.Timedelta(minutes=5)):
                raise ValueError(f"Invalid publication window: {path.name}")
            evidence = dict(snapshot["metadata"])
            inputs = evidence.pop("shadow")
            if (snapshot["model_sha256"] != model_hash or evidence != registration["model_metadata"]
                    or snapshot["horizon"] != config.horizon or snapshot["cost_bps"] != config.cost_bps
                    or inputs["registration_sha256"] != checksum
                    or inputs["feature_inputs_sha256"] != _digest(inputs["feature_inputs"])):
                raise ValueError(f"Forecast identity or feature checksum mismatch: {path.name}")
            features = pd.DataFrame(inputs["feature_inputs"])
            if (features.symbol.duplicated().any() or set(features.symbol) != set(config.symbols)
                    or not np.isfinite(features[FEATURES].to_numpy()).all()):
                raise ValueError(f"Incomplete or invalid archived features: {path.name}")
            valid_dates.add(str(date.date()))

        # Missing days remain visible without backfilling or changing performance denominators.
        for date in pd.date_range(first, expected_session):
            session = get_us_market_session(datetime.combine(date.date(), time(12), tzinfo=NEW_YORK_TZ))
            if session.market_close is None:
                continue
            deadline = pd.Timestamp(next_session_open(date))
            if registered >= deadline or str(date.date()) in valid_dates:
                continue
            key = "missing_dates" if now >= deadline else "pending_dates"
            row[key].append(str(date.date()))
        row["status"] = "ERROR" if row["missing_dates"] else "WARN" if row["pending_dates"] else "OK"
        row["detail"] = (f"frozen identity verified; forecasts={len(valid_dates)}; "
                         f"missed={row['missing_dates']}; pending={row['pending_dates']}")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        row.update(status="ERROR", detail=f"{type(exc).__name__}: {exc}")
    return row


def print_shadow_health(config: PredictionConfig | None = None) -> int:
    row = shadow_health(config)
    print(f"[{row['status']}] {row['check']}: {row['detail']}", flush=True)
    return int(row["status"] == "ERROR")
