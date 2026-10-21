"""Retain first-observed complete outcomes and append later data discrepancies."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from .prediction_data import write_json


VALUE_COLUMNS = ["entry_date", "label_end", "target", "gross_return"]


class OutcomeArchiveError(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _read_record(path):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        checksum = record.pop("record_sha256")
        if checksum != _digest(record):
            raise ValueError("checksum mismatch")
        return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise OutcomeArchiveError(f"Invalid outcome archive {path.name}: {exc}") from exc


def _write_record(path, record):
    if path.exists():
        if _read_record(path) != record:
            raise OutcomeArchiveError("Refusing to overwrite existing outcome evidence")
        return
    write_json(path, {**record, "record_sha256": _digest(record)})


def _values(frame):
    records = []
    for row in frame.sort_values("symbol").itertuples():
        item = {"symbol": row.symbol}
        for name in VALUE_COLUMNS:
            value = getattr(row, name)
            if name in {"target", "gross_return"} and not pd.isna(value) and not np.isfinite(float(value)):
                raise ValueError("Non-finite current outcome")
            item[name] = None if pd.isna(value) else pd.Timestamp(value).date().isoformat() if name in {
                "entry_date", "label_end"} else float(value)
        records.append(item)
    return records


@lru_cache(maxsize=2048)
def _session_count(entry_date, exit_date):
    return len(mcal.get_calendar("NYSE").valid_days(start_date=entry_date, end_date=exit_date))


def _validate(frame, entry, horizon, cost_bps, ceiling):
    mature = frame[VALUE_COLUMNS].notna().all(axis=1)
    if mature.any():
        observed = frame.loc[mature]
        if (not np.isfinite(observed[["target", "gross_return"]].to_numpy()).all()
                or not observed.target.isin([0, 1]).all()
                or not (observed.entry_date == pd.Timestamp(entry.date())).all()
                or not (observed.label_end > observed.entry_date).all()
                or not (observed.label_end == observed.label_end.dt.normalize()).all()
                or observed.label_end.nunique() != 1
                or not (observed.label_end <= ceiling).all()
                or not ((observed.gross_return > cost_bps / 10000).astype(int) == observed.target).all()):
            raise ValueError("Invalid realized outcome or entry/exit dates")
        if _session_count(entry.date(), observed.label_end.iloc[0].date()) != horizon + 1:
            raise ValueError("Realized outcome does not match the archived exchange-session horizon")
    return mature


def resolve_outcomes(predictions, realized, policy, config, forecast_hash, entry, data_as_of, *, timely):
    # Daily predictions hold the parent lock; this also protects standalone scorecard callers.
    from .prediction import prediction_lock

    root = config.output_dir / "observed_outcomes"
    day = policy["date"].date().isoformat()
    path = root / f"{day}.json"
    identity = {"schema": 1, "protocol": "first-observed-v1", "signal_date": day,
                "forecast_sha256": forecast_hash, "policy_key": policy["policy_key"]}
    info = {"outcome_source": "CURRENT_UNFROZEN", "outcome_check": "NOT_ARCHIVED",
            "outcome_review_required": False, "outcome_sha256": ""}
    ceiling = pd.Timestamp(data_as_of)
    with prediction_lock(root):
        saved = None
        if path.exists():
            saved = _read_record(path)
            try:
                if any(saved[key] != value for key, value in identity.items()):
                    raise ValueError("Forecast or policy differs from the first observation")
                first_seen = pd.Timestamp(saved["first_observed_at"])
                saved_ceiling = pd.Timestamp(saved["data_as_of"])
                if (first_seen.tzinfo is None or pd.isna(first_seen)
                        or first_seen > pd.Timestamp.now("UTC") + pd.Timedelta(minutes=5)
                        or saved_ceiling.tzinfo is not None or pd.isna(saved_ceiling)
                        or saved_ceiling > first_seen.tz_convert("America/New_York").tz_localize(None).normalize()):
                    raise ValueError("Invalid first-observation timestamps")
                frozen = pd.DataFrame(saved["outcomes"])
                if frozen.symbol.duplicated().any() or set(frozen.symbol) != set(predictions.symbol):
                    raise ValueError("Archived outcome universe is incomplete or changed")
                for name in ("entry_date", "label_end"):
                    frozen[name] = pd.to_datetime(frozen[name], errors="raise")
                archived = predictions.merge(frozen, on="symbol", how="left", validate="one_to_one")
                if not _validate(archived, entry, config.horizon, config.cost_bps, saved_ceiling).all():
                    raise ValueError("Archived outcomes are incomplete")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise OutcomeArchiveError(f"Invalid first-observed outcome: {exc}") from exc

        current, values, error = None, None, ""
        try:
            current = predictions.merge(realized, on="symbol", how="left", validate="one_to_one")
            mature = _validate(current, entry, config.horizon, config.cost_bps, ceiling)
            values = _values(current)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if saved is None:
                raise
            error = f"{type(exc).__name__}: {exc}"

        if saved is None:
            if timely and mature.all():
                saved = {**identity, "first_observed_at": pd.Timestamp.now("UTC").isoformat(),
                         "data_as_of": ceiling.date().isoformat(), "outcomes": values}
                _write_record(path, saved)
                info.update(outcome_source="FIRST_OBSERVED", outcome_check="FROZEN_NOW", outcome_sha256=_digest(saved))
            return current, mature, info

        check = "INVALID_CURRENT" if error else "UNAVAILABLE" if not mature.all() else "SAME" if values == saved["outcomes"] else "REVISED"
        revisions = config.output_dir / "outcome_revisions" / day
        if check != "SAME":
            discrepancy = {**identity, "first_outcome_sha256": _digest(saved), "check": check,
                           "current_outcomes": values, "error": error}
            revision_path = revisions / f"{_digest(discrepancy)}.json"
            if revision_path.exists():
                existing = _read_record(revision_path)
                if any(existing.get(key) != value for key, value in discrepancy.items()):
                    raise OutcomeArchiveError("Outcome discrepancy identity mismatch")
            else:
                _write_record(revision_path, {**discrepancy, "first_detected_at": pd.Timestamp.now("UTC").isoformat()})
        review = False
        for revision_path in revisions.glob("*.json"):
            _read_record(revision_path)
            review = True
        info.update(outcome_source="FIRST_OBSERVED", outcome_check=check,
                    outcome_review_required=review, outcome_sha256=_digest(saved))
        return archived, pd.Series(True, index=archived.index), info
