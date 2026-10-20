"""Score first-issued forecasts without retrospective policy changes or order execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from .market_calendar import get_us_market_session, next_session_open
from .prediction_data import PredictionConfig, file_hash, write_json


MIN_WINDOWS = 26
MIN_SIGNALS = 50
OUTCOME_COLUMNS = ["date", "symbol", "issued_at", "entry_date", "label_end", "probability", "target",
                   "gross_return", "model_sha256", "eligible_prospective", "exclusion_reason", "policy_key",
                   "threshold", "top_k", "rank_selected", "net_return"]
SCORE_COLUMNS = ["policy_key", "model_sha256", "threshold", "top_k", "first_date", "last_date", "rows", "dates",
                 "nonoverlap_windows", "classification_accuracy", "always_positive_accuracy", "brier",
                 "half_probability_brier", "signal_count", "signal_hit_rate", "ranked_signal_count",
                 "ranked_signal_hit_rate", "ranked_signal_windows", "evidence_status"]


def _write_frame(path: Path, frame: pd.DataFrame):
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)


def _snapshot(path: Path, config: PredictionConfig) -> tuple[dict, pd.DataFrame, dict]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    date = pd.Timestamp(snapshot["as_of"])
    issued = pd.Timestamp(snapshot["issued_at"])
    if pd.isna(date) or date.tzinfo is not None or date != date.normalize():
        raise ValueError("Invalid signal date")
    if date.date().isoformat() != path.stem:
        raise ValueError("Snapshot filename and signal date disagree")
    if pd.isna(issued) or issued.tzinfo is None:
        raise ValueError("Issue timestamp must include its timezone")
    predictions = pd.DataFrame(snapshot["predictions"])[["symbol", "probability"]].copy()
    if predictions.empty or predictions.symbol.isna().any() or predictions.symbol.duplicated().any():
        raise ValueError("Missing or duplicate forecast symbols")
    predictions["probability"] = pd.to_numeric(predictions.probability, errors="raise")
    if not np.isfinite(predictions.probability).all() or not predictions.probability.between(0, 1).all():
        raise ValueError("Invalid forecast probabilities")
    metadata = snapshot.get("metadata", {})
    settings = metadata.get("config", {})
    expected = settings.get("symbols", config.symbols)
    if set(predictions.symbol) != set(expected):
        raise ValueError("Forecast universe is incomplete or changed")
    for cutoff in (metadata.get("training_last_label_date"), settings.get("validation_end")):
        if cutoff is not None and pd.Timestamp(cutoff) > date:
            raise ValueError("Model selection or training used observations after the signal date")
    threshold = metadata.get("threshold")
    if threshold is not None and (not np.isfinite(float(threshold)) or not 0 <= float(threshold) <= 1):
        raise ValueError("Invalid archived threshold")
    top_k = settings.get("top_k", config.top_k)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("Invalid archived position count")
    policy = {"model_sha256": snapshot["model_sha256"], "threshold": threshold, "top_k": top_k,
              "horizon": snapshot["horizon"], "cost_bps": snapshot["cost_bps"], "symbols": sorted(predictions.symbol)}
    if not isinstance(policy["model_sha256"], str) or not policy["model_sha256"]:
        raise ValueError("Missing model identity")
    if not np.isfinite(float(policy["cost_bps"])) or float(policy["cost_bps"]) < 0:
        raise ValueError("Invalid archived costs")
    key = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    predictions = predictions.sort_values(["probability", "symbol"], ascending=[False, True]).reset_index(drop=True)
    predictions["rank_selected"] = (predictions.probability >= float(threshold)) & (predictions.index < top_k) if threshold is not None else False
    return snapshot, predictions, {**policy, "policy_key": key, "date": date, "issued_at": issued}


def _windows(frame: pd.DataFrame) -> int:
    count, previous_exit = 0, pd.Timestamp.min
    for _, cohort in frame.groupby("date", sort=True):
        entry, exit_date = cohort.entry_date.iloc[0], cohort.label_end.iloc[0]
        if entry >= previous_exit:
            count += 1
            previous_exit = exit_date
    return count


def _metrics(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"rows": 0, "dates": 0, "nonoverlap_windows": 0, "classification_accuracy": None,
                "always_positive_accuracy": None, "brier": None, "half_probability_brier": None,
                "signal_count": 0, "signal_hit_rate": None, "ranked_signal_count": 0,
                "ranked_signal_hit_rate": None, "ranked_signal_windows": 0,
                "evidence_status": "INSUFFICIENT_PROSPECTIVE_DATA"}
    signals = frame.loc[frame.threshold.notna() & (frame.probability >= frame.threshold)]
    ranked = frame.loc[frame.rank_selected]
    windows = _windows(ranked)
    return {"rows": len(frame), "dates": frame.date.nunique(), "nonoverlap_windows": _windows(frame),
            "classification_accuracy": float(((frame.probability >= .5) == frame.target).mean()),
            "always_positive_accuracy": float(frame.target.mean()),
            "brier": float(((frame.probability - frame.target) ** 2).mean()), "half_probability_brier": .25,
            "signal_count": len(signals), "signal_hit_rate": float(signals.target.mean()) if len(signals) else None,
            "ranked_signal_count": len(ranked), "ranked_signal_hit_rate": float(ranked.target.mean()) if len(ranked) else None,
            "ranked_signal_windows": windows,
            "evidence_status": "MIXED_POLICIES" if frame.policy_key.nunique() > 1 else "MONITORING_ONLY" if windows >= MIN_WINDOWS and len(ranked) >= MIN_SIGNALS else "INSUFFICIENT_PROSPECTIVE_DATA"}


def evaluate_prospective(dataset: pd.DataFrame, config: PredictionConfig) -> dict:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted((config.output_dir / "issued").glob("*.json"))
    rows, inventory = [], []
    for path in paths:
        record = {"file": path.name, "status": "INVALID", "reason": "", "forecast_rows": 0, "mature_rows": 0}
        try:
            record["snapshot_sha256"] = file_hash(path)
            snapshot, predictions, policy = _snapshot(path, config)
            record.update(as_of=str(policy["date"].date()), model_sha256=policy["model_sha256"],
                          policy_key=policy["policy_key"], forecast_rows=len(predictions))
            if snapshot["horizon"] != config.horizon or snapshot["cost_bps"] != config.cost_bps:
                record.update(status="INCOMPATIBLE_POLICY", reason="Archived horizon/cost differs from current outcome labels")
                continue
            signal_session = get_us_market_session(pd.Timestamp(policy["date"], tz="America/New_York").replace(hour=12).to_pydatetime())
            entry = next_session_open(policy["date"])
            if signal_session.market_close is None:
                raise ValueError("Signal date is not a trading session")
            issue_time = policy["issued_at"]
            if issue_time > pd.Timestamp.now("UTC") + pd.Timedelta(minutes=5):
                reason = "FUTURE_ISSUE_TIME"
            elif issue_time < pd.Timestamp(signal_session.market_close) + pd.Timedelta(minutes=30):
                reason = "BEFORE_DATA_AVAILABLE"
            elif issue_time >= pd.Timestamp(entry):
                reason = "LATE_ISSUE"
            else:
                reason = ""
            realized = dataset.loc[dataset.date == policy["date"], ["symbol", "entry_date", "label_end", "target", "gross_return"]]
            merged = predictions.merge(realized, on="symbol", how="left", validate="one_to_one")
            mature = merged[["entry_date", "label_end", "target", "gross_return"]].notna().all(axis=1)
            record["mature_rows"] = int(mature.sum())
            if mature.any():
                observed = merged.loc[mature]
                if (not np.isfinite(observed[["target", "gross_return"]].to_numpy()).all()
                        or not observed.target.isin([0, 1]).all()
                        or not (observed.entry_date == pd.Timestamp(entry.date())).all()
                        or not (observed.label_end > observed.entry_date).all()
                        or observed.label_end.nunique() != 1
                        or not (observed.label_end <= dataset.date.max()).all()
                        or not ((observed.gross_return > config.cost_bps / 10000).astype(int) == observed.target).all()):
                    raise ValueError("Invalid realized outcome or entry/exit dates")
                sessions = mcal.get_calendar("NYSE").valid_days(start_date=entry.date(), end_date=observed.label_end.iloc[0].date())
                if len(sessions) != config.horizon + 1:
                    raise ValueError("Realized outcome does not match the archived exchange-session horizon")
            if not reason and not mature.all():
                reason = "INCOMPLETE_OUTCOMES" if mature.any() else "WAITING_OUTCOMES"
            record.update(status=reason or "MATURE", reason=reason)
            merged["date"] = policy["date"]
            merged["issued_at"] = issue_time.isoformat()
            merged["model_sha256"] = policy["model_sha256"]
            merged["policy_key"] = policy["policy_key"]
            merged["threshold"] = float(policy["threshold"]) if policy["threshold"] is not None else np.nan
            merged["top_k"] = policy["top_k"]
            merged["net_return"] = merged.gross_return - config.cost_bps / 10000
            merged["eligible_prospective"] = not reason
            merged["exclusion_reason"] = reason
            rows.append(merged.loc[mature, OUTCOME_COLUMNS])
        except (OSError, ValueError, KeyError, TypeError, AttributeError, pd.errors.MergeError) as exc:
            record.update(status="INVALID", reason=f"{type(exc).__name__}: {exc}")
        finally:
            inventory.append(record)
    outcomes = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=OUTCOME_COLUMNS)
    eligible = outcomes.loc[outcomes.eligible_prospective == True]
    scorecard, reliability = [], []
    for policy_key, group in eligible.groupby("policy_key", sort=False):
        first = group.iloc[0]
        scorecard.append({"policy_key": policy_key, "model_sha256": first.model_sha256,
                          "threshold": None if pd.isna(first.threshold) else float(first.threshold), "top_k": int(first.top_k),
                          "first_date": str(group.date.min().date()), "last_date": str(group.date.max().date()), **_metrics(group)})
        for bucket, values in group.groupby(pd.cut(group.probability, np.linspace(0, 1, 11), include_lowest=True), observed=True):
            reliability.append({"policy_key": policy_key, "model_sha256": first.model_sha256, "bucket": str(bucket),
                                "rows": len(values), "dates": values.date.nunique(),
                                "mean_probability": float(values.probability.mean()), "actual_positive_rate": float(values.target.mean())})
    score_frame = pd.DataFrame(scorecard, columns=SCORE_COLUMNS)
    if not score_frame.empty:
        score_frame = score_frame.sort_values(["last_date", "policy_key"], ascending=[False, True])
    inventory_frame = pd.DataFrame(inventory, columns=["file", "as_of", "status", "reason", "forecast_rows", "mature_rows", "model_sha256", "policy_key", "snapshot_sha256"])
    model_path = config.output_dir / "model.joblib"
    current_hash = file_hash(model_path) if model_path.exists() else ""
    current = eligible.loc[eligible.model_sha256 == current_hash]
    pooled = _metrics(eligible)
    # Never label pooled observations across model versions as a validated current model.
    result = {"issued_days": len(paths), "mature_rows": len(outcomes), "eligible_rows": len(eligible),
              "eligible_dates": int(pooled["dates"]), "brier": pooled["brier"],
              "classification_accuracy": pooled["classification_accuracy"],
              "always_positive_accuracy": pooled["always_positive_accuracy"],
              "evidence_status": _metrics(current)["evidence_status"], "current_model": _metrics(current),
              "current_model_sha256": current_hash, "policy_count": len(scorecard),
              "status_counts": {str(k): int(v) for k, v in inventory_frame.status.value_counts().items()},
              "trading_enabled": False,
              "protocol": {"minimum_nonoverlap_signal_windows": MIN_WINDOWS, "minimum_ranked_signals": MIN_SIGNALS,
                           "selection": "Archived threshold and top_k; fixed probability rank with symbol tie-break",
                           "evidence": "Descriptive monitoring only; never auto-promote or tune against realized outcomes",
                           "baseline": "Always-positive net-return classifier; constant 0.5 probability Brier baseline",
                           "limitations": "Overlapping ranked signals are not a cash-constrained trading ledger; no trade win rate or independent-sample claim"}}
    _write_frame(config.output_dir / "issued_outcomes.csv", outcomes)
    _write_frame(config.output_dir / "prospective_inventory.csv", inventory_frame)
    _write_frame(config.output_dir / "prospective_scorecard.csv", score_frame)
    _write_frame(config.output_dir / "prospective_reliability.csv", pd.DataFrame(reliability, columns=["policy_key", "model_sha256", "bucket", "rows", "dates", "mean_probability", "actual_positive_rate"]))
    write_json(config.output_dir / "prospective_report.json", result)
    lines = ["# Prospective Forecast Scorecard", "", f"Current model evidence: {result['evidence_status']}; trading enabled: false",
             f"Issued dates: {len(paths)}; eligible mature dates: {result['eligible_dates']}; eligible rows: {len(eligible)}.",
             "No mature sample is N/A, never 0% accuracy or a successful validation.", "",
             "Classification accuracy is the >=0.5 prediction of a positive return AFTER configured costs, not raw price direction.",
             "Signal hit rates use archived thresholds and ranks. They are not realized trading win rates.",
             "Models/policies are separated; current-model evidence is not borrowed from older models.", "",
             "| Model | Dates | Rows | Net-direction accuracy | Always positive | Ranked signals | Ranked signal hit rate | Nonoverlap signal windows |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in score_frame.to_dict("records"):
        hit = "N/A" if row["ranked_signal_hit_rate"] is None else f"{row['ranked_signal_hit_rate']:.2%}"
        lines.append(f"| {row['model_sha256'][:12]} | {row['dates']} | {row['rows']} | {row['classification_accuracy']:.2%} | {row['always_positive_accuracy']:.2%} | {row['ranked_signal_count']} | {hit} | {row['ranked_signal_windows']} |")
    lines += ["", "## Eligibility", "",
              "Require publication after the signal session's close + 30 minutes and before the next session's open.",
              "The entire archived universe must have valid mature outcomes; partial cohorts are not scored.",
              f"At least {MIN_WINDOWS} nonoverlapping signal windows and {MIN_SIGNALS} ranked signals per model/policy are needed even for monitoring status.",
              "These counts do not prove profitability, statistical independence or readiness for live trading.", ""]
    lines += [f"- {key}: {value}" for key, value in result["status_counts"].items()]
    (config.output_dir / "prospective_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
