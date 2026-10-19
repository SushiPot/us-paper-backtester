"""Chronological prediction experiments. Never submits or enables orders."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .market_calendar import NEW_YORK_TZ, get_us_market_session
from .prediction_data import PredictionConfig, PredictionDataStore, completed_session, file_hash, write_json
from .prediction_features import FEATURES, build_dataset, time_partitions


@contextmanager
def prediction_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".run.lock").open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temp, index=False, encoding="utf-8-sig")
    temp.replace(path)


def probability_metrics(frame: pd.DataFrame, probability, prior: float) -> dict:
    y = frame.target.astype(int)
    return {
        "rows": len(frame), "dates": frame.date.nunique(), "symbols": frame.symbol.nunique(),
        "brier": float(brier_score_loss(y, probability)),
        "baseline_brier": float(brier_score_loss(y, np.full(len(y), prior))),
        "auc": float(roc_auc_score(y, probability)) if y.nunique() == 2 else None,
    }


def portfolio_blocks(frame: pd.DataFrame, threshold: float, config: PredictionConfig) -> pd.DataFrame:
    """One non-overlapping horizon sleeve, with unused position slots held in cash."""
    rows = []
    next_entry = pd.Timestamp.min
    for date, group in frame.groupby("date", sort=True):
        if "complete_outcomes" in group and not group.complete_outcomes.all():
            continue
        entry = group.entry_date.iloc[0]
        if entry < next_entry:
            continue
        next_entry = group.label_end.iloc[0]
        chosen = group.loc[group.probability >= threshold].sort_values(
            ["probability", "symbol"], ascending=[False, True]).head(config.top_k)
        cost = config.cost_bps / 10000
        rows.append({"date": date, "entry_date": entry, "exit_date": next_entry,
                     "positions": len(chosen), "exposure": len(chosen) / config.top_k,
                     "net_return": float((chosen.gross_return - cost).sum() / config.top_k),
                     "stress_return": float((chosen.gross_return - 2 * cost).sum() / config.top_k),
                     "universe_return": float(group.gross_return.mean() - cost),
                     "spy_return": float(group.spy_return.iloc[0] - cost)})
    return pd.DataFrame(rows)


def block_metrics(blocks: pd.DataFrame, config: PredictionConfig) -> dict:
    if blocks.empty:
        return {"blocks": 0, "trades": 0, "active_blocks": 0, "total_return": 0.0,
                "stress_total_return": 0.0, "universe_total_return": 0.0, "spy_total_return": 0.0,
                "max_drawdown": 0.0, "mean_conservative_excess": 0.0,
                "excess_ci95_low": 0.0, "excess_ci95_high": 0.0, "positive_excess_fraction": 0.0}
    returns = blocks.net_return.to_numpy()
    equity = np.cumprod(1 + returns)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    excess = returns - np.maximum(blocks.universe_return, blocks.spy_return).to_numpy()
    # Resample entire horizon blocks, not correlated individual stock observations.
    rng = np.random.default_rng(config.seed)
    samples = rng.choice(excess, size=(1000, len(excess)), replace=True).mean(axis=1)
    return {"blocks": len(blocks), "trades": int(blocks.positions.sum()),
            "active_blocks": int((blocks.positions > 0).sum()),
            "total_return": float(equity[-1] - 1),
            "stress_total_return": float((1 + blocks.stress_return).prod() - 1),
            "universe_total_return": float((1 + blocks.universe_return).prod() - 1),
            "spy_total_return": float((1 + blocks.spy_return).prod() - 1),
            "max_drawdown": float((equity / peaks - 1).min()),
            "mean_conservative_excess": float(excess.mean()),
            "excess_ci95_low": float(np.quantile(samples, .025)),
            "excess_ci95_high": float(np.quantile(samples, .975)),
            "positive_excess_fraction": float((excess > 0).mean())}


def candidate_models(seed: int) -> dict:
    return {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=500, random_state=seed)),
        "hist_gradient": HistGradientBoostingClassifier(max_iter=120, max_leaf_nodes=15,
                                                         learning_rate=.05, l2_regularization=10,
                                                         early_stopping=False, random_state=seed),
    }


def fit_select(train: pd.DataFrame, validation: pd.DataFrame, config: PredictionConfig):
    """Selection has no access to test or forward labels."""
    prior = float(train.target.mean())
    models, scores = candidate_models(config.seed), []
    with threadpool_limits(limits=2):
        for name, model in models.items():
            print(f"[TRAIN] {name}: rows={len(train)}", flush=True)
            model.fit(train[FEATURES], train.target.astype(int))
            probability = model.predict_proba(validation[FEATURES])[:, 1]
            scores.append({"model": name, **probability_metrics(validation, probability, prior)})
    scores = pd.DataFrame(scores).sort_values(["brier", "model"])
    selected = str(scores.iloc[0].model)
    model = models[selected]
    with threadpool_limits(limits=2):
        validation = validation.assign(probability=model.predict_proba(validation[FEATURES])[:, 1])
    thresholds = []
    for threshold in (.50, .55, .60, .65):
        thresholds.append({"threshold": threshold, **block_metrics(portfolio_blocks(validation, threshold, config), config)})
    thresholds = pd.DataFrame(thresholds)
    eligible = thresholds.loc[(thresholds.trades >= 50) & (thresholds.active_blocks >= 26)]
    threshold = .55 if eligible.empty else float(eligible.sort_values(
        ["mean_conservative_excess", "threshold"], ascending=[False, True]).iloc[0].threshold)
    return model, selected, threshold, prior, scores, thresholds


def gate_reasons(metrics: dict, blocks: pd.DataFrame, name: str) -> list[str]:
    reasons = []
    if metrics.get("blocks", 0) < 26 or metrics.get("trades", 0) < 50:
        reasons.append(f"{name}: insufficient independent trading observations")
    if metrics.get("brier", 1) >= metrics.get("baseline_brier", 0):
        reasons.append(f"{name}: probabilities do not beat training-prior baseline")
    if metrics.get("excess_ci95_low", -1) <= 0:
        reasons.append(f"{name}: excess-return confidence interval includes zero")
    if metrics.get("stress_total_return", -1) <= 0 or metrics.get("max_drawdown", -1) < -.20:
        reasons.append(f"{name}: cost stress or drawdown gate failed")
    if not blocks.empty:
        for year, group in blocks.groupby(pd.to_datetime(blocks.date).dt.year):
            if len(group) >= 26 and group.net_return.mean() <= max(group.universe_return.mean(), group.spy_return.mean()):
                reasons.append(f"{name}: no positive benchmark edge in {year}")
    return reasons


def _config_dict(config):
    return {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()}


def record_forecast(latest: pd.DataFrame, config: PredictionConfig, metadata: dict, as_of) -> None:
    """Keep the first issued forecast each day; reruns cannot rewrite its history."""
    path = config.output_dir / "issued" / f"{as_of.date()}.json"
    if latest.empty or path.exists():
        return
    write_json(path, {"issued_at": pd.Timestamp.now("UTC").isoformat(), "as_of": str(as_of.date()),
                      "horizon": config.horizon, "cost_bps": config.cost_bps,
                      "model_sha256": file_hash(config.output_dir / "model.joblib"),
                      "metadata": metadata,
                      "predictions": latest[["symbol", "probability"]].to_dict("records")})


def evaluate_issued(dataset: pd.DataFrame, config: PredictionConfig) -> dict:
    rows = []
    snapshots = list((config.output_dir / "issued").glob("*.json"))
    for path in sorted(snapshots):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if snapshot["horizon"] != config.horizon or snapshot["cost_bps"] != config.cost_bps:
            continue
        realized = dataset.loc[dataset.date == pd.Timestamp(snapshot["as_of"])].dropna(subset=["target"])
        if realized.empty:
            continue
        entry = pd.Timestamp(realized.entry_date.iloc[0]).tz_localize(NEW_YORK_TZ) + pd.Timedelta(hours=12)
        market_open = get_us_market_session(entry.to_pydatetime()).market_open
        # A prediction published after its assumed execution time is not prospective evidence.
        timely = market_open is not None and pd.Timestamp(snapshot["issued_at"]) < pd.Timestamp(market_open)
        merged = realized.merge(pd.DataFrame(snapshot["predictions"]), on="symbol", validate="one_to_one")
        merged["issued_at"] = snapshot["issued_at"]
        merged["model_sha256"] = snapshot["model_sha256"]
        merged["eligible_prospective"] = timely
        rows.append(merged)
    columns = ["date", "symbol", "issued_at", "entry_date", "label_end", "probability", "target",
               "gross_return", "model_sha256", "eligible_prospective"]
    outcomes = pd.concat(rows, ignore_index=True)[columns] if rows else pd.DataFrame(columns=columns)
    write_frame(config.output_dir / "issued_outcomes.csv", outcomes)
    eligible = outcomes.loc[outcomes.eligible_prospective == True]
    return {"issued_days": len(snapshots), "mature_rows": len(outcomes), "eligible_rows": len(eligible),
            "eligible_dates": eligible.date.nunique(),
            "brier": float(brier_score_loss(eligible.target.astype(int), eligible.probability)) if not eligible.empty else None}


def run_prediction(config: PredictionConfig | None = None, *, refresh=False, max_downloads=60) -> dict:
    config = config or PredictionConfig()
    with prediction_lock(config.output_dir):
        status_path = config.output_dir / "status.json"
        write_json(status_path, {"status": "RUNNING", "updated_at": pd.Timestamp.now("UTC").isoformat(), "trading_enabled": False})
        try:
            report = _run(config, refresh, max_downloads)
            write_json(status_path, report)
            return report
        except Exception as exc:
            write_json(status_path, {"status": "ERROR", "updated_at": pd.Timestamp.now("UTC").isoformat(),
                                     "error": f"{type(exc).__name__}: {exc}", "trading_enabled": False})
            raise


def _run(config, refresh, max_downloads):
    as_of = completed_session()
    frames, inventory = PredictionDataStore(config).load(refresh=refresh, max_downloads=max_downloads, as_of=as_of)
    write_frame(config.output_dir / "data_inventory.csv", inventory)
    dataset = build_dataset(frames, config)
    parts = time_partitions(dataset, config)
    model, name, threshold, prior, scores, thresholds = fit_select(parts["train"], parts["validation"], config)
    write_frame(config.output_dir / "model_comparison.csv", scores)
    write_frame(config.output_dir / "threshold_validation.csv", thresholds)
    metrics, all_blocks, reliability, reasons = {}, [], [], []
    for part_name in ("validation", "test", "forward"):
        part = parts[part_name]
        if part.empty:
            reasons.append(f"{part_name}: no mature labels")
            continue
        with threadpool_limits(limits=2):
            probability = model.predict_proba(part[FEATURES])[:, 1]
        scored = part.assign(probability=probability)
        blocks = portfolio_blocks(scored, threshold, config)
        metrics[part_name] = {**probability_metrics(part, probability, prior), **block_metrics(blocks, config)}
        all_blocks.append(blocks.assign(partition=part_name))
        reasons.extend(gate_reasons(metrics[part_name], blocks, part_name))
        for bucket, group in scored.groupby(pd.cut(scored.probability, np.linspace(0, 1, 11), include_lowest=True), observed=True):
            reliability.append({"partition": part_name, "bucket": str(bucket), "rows": len(group),
                                "mean_probability": group.probability.mean(), "actual_positive_rate": group.target.mean()})
        if part_name == "test":
            write_frame(config.output_dir / "holdout_predictions.csv", scored[["date", "symbol", "label_end", "target", "gross_return", "probability"]])
    data_ready = bool((inventory.status == "CURRENT").all() and len(frames) == len(inventory))
    if not data_ready:
        reasons.append("One or more symbols have missing/stale verified history")
    latest = dataset.loc[dataset.date == as_of].copy()
    if latest.symbol.nunique() != len(set(config.symbols)):
        data_ready = False
        reasons.append("Latest feature coverage is incomplete")
    if latest.empty:
        reasons.append("No predictions for latest completed session")
        latest["probability"] = pd.Series(dtype=float)
    else:
        with threadpool_limits(limits=2):
            latest["probability"] = model.predict_proba(latest[FEATURES])[:, 1]
    latest = latest[["date", "symbol", "probability"]].sort_values(["probability", "symbol"], ascending=[False, True])
    latest["above_research_threshold"] = latest.probability >= threshold
    latest["trading_enabled"] = False
    write_frame(config.output_dir / "latest_predictions.csv", latest)
    write_frame(config.output_dir / "portfolio_blocks.csv", pd.concat(all_blocks, ignore_index=True))
    write_frame(config.output_dir / "probability_reliability.csv", pd.DataFrame(reliability))
    data_fingerprint = hashlib.sha256(json.dumps(inventory[["symbol", "sha256"]].to_dict("records"), sort_keys=True).encode()).hexdigest()
    metadata = {"features": FEATURES, "config": _config_dict(config), "selected_model": name,
                "threshold": threshold, "sklearn_version": sklearn.__version__, "data_fingerprint": data_fingerprint,
                "training_last_label_date": str(parts["train"].label_end.max().date())}
    model_temp = config.output_dir / "model.joblib.tmp"
    joblib.dump({"model": model, "metadata": metadata}, model_temp)
    model_temp.replace(config.output_dir / "model.joblib")
    if data_ready:
        record_forecast(latest, config, metadata, as_of)
    prospective = evaluate_issued(dataset, config)
    report = {"status": "RESEARCH_PASS" if not reasons else "RESEARCH_ONLY", "trading_enabled": False,
              "updated_at": pd.Timestamp.now("UTC").isoformat(), "as_of": str(as_of.date()),
              "model": name, "threshold": threshold, "data_ready": data_ready,
              "total_feature_rows": len(dataset), "verified_symbols": len(frames),
              "split_dates": {key: {"first": str(value.date.min().date()), "last": str(value.date.max().date()),
                                    "last_label": str(value.label_end.max().date()), "rows": len(value)}
                              for key, value in parts.items() if not value.empty},
              "metrics": metrics, "reasons": reasons, "metadata": metadata, "prospective": prospective,
              "limitations": ["Current configured universe has survivorship bias; delisted stocks are not represented.",
                              "Only causal adjusted OHLCV features; latest SEC/FRED snapshots are deliberately excluded.",
                              "Fixed historical study, not a live validated or continuously refitted trading model.",
                              "The forward partition is retrospective 2026 data, not previously issued live predictions.",
                              "Block confidence interval is exploratory and does not eliminate regime dependence.",
                              "Raw model probabilities require forward monitoring; no guarantee of calibration."]}
    write_json(config.output_dir / "report.json", report)
    lines = ["# Prediction Research Report", "", f"Status: {report['status']}; trading enabled: false",
             f"As of: {report['as_of']}; model: {name}; research threshold: {threshold:.2f}",
             f"Verified symbols: {len(frames)}; feature rows: {len(dataset)}", "",
             "Signals use completed-session features; simulated entry is the next open, exit five sessions later by default.",
             "Position slots not selected remain cash. Model and threshold selection use validation data only.", "",
             f"Actually issued forecast days: {prospective['issued_days']}; mature prospective dates: {prospective['eligible_dates']}.",
             "The forward table below is retrospective; it is not evidence of live prediction performance.", "",
             "## Evaluation", "", "| Period | Brier | Prior baseline | Net return | SPY | Universe | Drawdown |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for period, values in metrics.items():
        lines.append(f"| {period} | {values['brier']:.4f} | {values['baseline_brier']:.4f} | {values['total_return']:.2%} | {values['spy_total_return']:.2%} | {values['universe_total_return']:.2%} | {values['max_drawdown']:.2%} |")
    lines += ["", "## Gate Results", ""] + [f"- {reason}" for reason in reasons or ["Research checks passed; forward paper validation still required."]]
    lines += ["", "## Limitations", ""] + [f"- {item}" for item in report["limitations"]]
    (config.output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[RESULT] {report['status']}: {len(frames)} symbols, {len(dataset)} feature rows; trading disabled", flush=True)
    return report
