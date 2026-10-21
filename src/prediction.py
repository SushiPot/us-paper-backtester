"""Chronological prediction experiments. Never submits or enables orders."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import ast
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

from .market_calendar import next_session_open, now_new_york
from .prediction_data import PredictionConfig, PredictionDataStore, completed_session, file_hash, write_json
from .prediction_features import FEATURES, build_dataset, time_partitions
from .prediction_portfolio import EXECUTION_PROTOCOL, PortfolioDataError, compare_execution, execution_sensitivity


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
        net_trades = chosen.gross_return - cost
        rows.append({"date": date, "entry_date": entry, "exit_date": next_entry,
                     "positions": len(chosen), "exposure": len(chosen) / config.top_k,
                     "winning_trades": int((net_trades > 0).sum()),
                     "losing_trades": int((net_trades < 0).sum()),
                     "winning_return_sum": float(net_trades.loc[net_trades > 0].sum()),
                     "losing_return_sum": float(net_trades.loc[net_trades < 0].sum()),
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
                "excess_ci95_low": 0.0, "excess_ci95_high": 0.0, "positive_excess_fraction": 0.0,
                "winning_trades": 0, "losing_trades": 0, "trade_win_rate": None,
                "average_win": None, "average_loss": None, "profit_factor": None}
    returns = blocks.net_return.to_numpy()
    equity = np.cumprod(1 + returns)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    excess = returns - np.maximum(blocks.universe_return, blocks.spy_return).to_numpy()
    # Resample entire horizon blocks, not correlated individual stock observations.
    rng = np.random.default_rng(config.seed)
    samples = rng.choice(excess, size=(1000, len(excess)), replace=True).mean(axis=1)
    trades = int(blocks.positions.sum())
    wins, losses = int(blocks.winning_trades.sum()), int(blocks.losing_trades.sum())
    win_sum, loss_sum = float(blocks.winning_return_sum.sum()), float(blocks.losing_return_sum.sum())
    return {"blocks": len(blocks), "trades": int(blocks.positions.sum()),
            "winning_trades": wins, "losing_trades": losses,
            "trade_win_rate": wins / trades if trades else None,
            "average_win": win_sum / wins if wins else None,
            "average_loss": loss_sum / losses if losses else None,
            "profit_factor": win_sum / abs(loss_sum) if loss_sum < 0 else None,
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


def _training_code_fingerprint(source: str | None = None) -> str:
    # Keep this set complete when adding helpers used by fitting or threshold selection.
    names = {"candidate_models", "fit_select", "portfolio_blocks", "block_metrics", "probability_metrics"}
    tree = ast.parse(source if source is not None else Path(__file__).read_text(encoding="utf-8"))
    nodes = {node.name: ast.dump(node, include_attributes=False) for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in names}
    if set(nodes) != names:
        raise ValueError("Training fingerprint is missing a required fitting/selection function")
    return hashlib.sha256(json.dumps(nodes, sort_keys=True).encode()).hexdigest()


def _fit_or_load(parts, config, data_fingerprint, *, retrain=False):
    settings = {key: value for key, value in _config_dict(config).items()
                if key not in {"cache_dir", "output_dir", "request_interval"}}
    digest = hashlib.sha256(json.dumps({"config": settings, "sklearn": sklearn.__version__,
                                        "pandas": pd.__version__, "numpy": np.__version__,
                                        "training_code": _training_code_fingerprint(),
                                        "cache_protocol": 2,
                                        "features": file_hash(Path(__file__).with_name("prediction_features.py"))},
                                       sort_keys=True).encode())
    for partition in ("train", "validation"):
        columns = ["date", "symbol", "label_end", "target", "gross_return", "spy_return", *FEATURES]
        values = parts[partition][columns].copy()
        # Equal dates from Yahoo seconds and CSV microseconds must share a training identity.
        for column in ("date", "label_end"):
            values[column] = values[column].dt.as_unit("us")
        digest.update(pd.util.hash_pandas_object(values, index=False).to_numpy().tobytes())
    key = digest.hexdigest()
    model_path = config.output_dir / "model.joblib"
    manifest_path = config.output_dir / "model_manifest.json"
    if not retrain:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest["input_key"] == key and manifest["model_sha256"] == file_hash(model_path):
                artifact = joblib.load(model_path)
                print("[MODEL] Reusing verified model; training/validation inputs unchanged", flush=True)
                return artifact["model"], artifact["metadata"], manifest, "REUSED"
        except (OSError, ValueError, KeyError, TypeError, EOFError):
            pass
    model, name, threshold, prior, scores, thresholds = fit_select(parts["train"], parts["validation"], config)
    write_frame(config.output_dir / "model_comparison.csv", scores)
    write_frame(config.output_dir / "threshold_validation.csv", thresholds)
    metadata = {"features": FEATURES, "config": _config_dict(config), "selected_model": name,
                "threshold": threshold, "sklearn_version": sklearn.__version__, "data_fingerprint": data_fingerprint,
                "training_key": key, "training_last_label_date": str(parts["train"].label_end.max().date())}
    temp = model_path.with_suffix(".joblib.tmp")
    joblib.dump({"model": model, "metadata": metadata}, temp)
    temp.replace(model_path)
    manifest = {"input_key": key, "model_sha256": file_hash(model_path), "prior": prior,
                "trained_at": pd.Timestamp.now("UTC").isoformat()}
    write_json(manifest_path, manifest)
    return model, metadata, manifest, "TRAINED"


def _latest_state(dataset, inventory, model, threshold, config, as_of):
    latest = dataset.loc[dataset.date == as_of].copy()
    ready = bool((inventory.status == "CURRENT").all() and latest.symbol.nunique() == len(set(config.symbols)))
    if latest.empty:
        latest["probability"] = pd.Series(dtype=float)
    else:
        with threadpool_limits(limits=2):
            latest["probability"] = model.predict_proba(latest[FEATURES])[:, 1]
    entry_open = next_session_open(as_of)
    missed = now_new_york() >= entry_open
    qualified = int((latest.probability >= threshold).sum())
    action = "WAIT_FOR_FRESH_DATA" if not ready else "WAIT_FOR_NEXT_CLOSE" if missed else "NO_QUALIFIED_SIGNAL" if not qualified else "OBSERVE_ONLY"
    context = {"action": action, "expected_session": str(as_of.date()),
               "qualified_signal_count": qualified,
               "next_entry_open": entry_open.isoformat(), "entry_window_missed": missed,
               "daily_bar_policy": "Completed daily bars only; quote snapshots are indicative and not model features"}
    latest = latest[["date", "symbol", "probability"]].sort_values(["probability", "symbol"], ascending=[False, True])
    latest["above_research_threshold"] = latest.probability >= threshold
    latest["decision"] = action
    latest["trading_enabled"] = False
    return latest, ready, context


def _daily_report(dataset, inventory, model, metadata, manifest, model_action, config, store, as_of, refresh):
    latest, ready, context = _latest_state(dataset, inventory, model, metadata["threshold"], config, as_of)
    quotes = store.quotes(["SPY", *latest.symbol.head(config.top_k).tolist()], refresh=refresh)
    latest = latest.merge(quotes.drop(columns=["source", "error"]), on="symbol", how="left", validate="one_to_one")
    write_frame(config.output_dir / "latest_predictions.csv", latest)
    write_frame(config.output_dir / "market_quotes.csv", quotes)
    if ready:
        record_forecast(latest, config, metadata, as_of)
    prospective = evaluate_issued(dataset, config)
    research = {}
    try:
        previous = json.loads((config.output_dir / "research_report.json").read_text(encoding="utf-8"))
        if isinstance(previous, dict) and previous.get("model_sha256") == manifest["model_sha256"]:
            research = previous
    except (OSError, ValueError, TypeError):
        pass
    fingerprint = hashlib.sha256(json.dumps(inventory[["symbol", "sha256"]].to_dict("records"), sort_keys=True).encode()).hexdigest()
    report = {"status": "RESEARCH_ONLY" if ready else "STALE_DATA", "mode": "DAILY", "trading_enabled": False,
              "updated_at": pd.Timestamp.now("UTC").isoformat(), "as_of": str(as_of.date()),
              "data_ready": ready, "model": metadata["selected_model"], "threshold": metadata["threshold"],
              "model_action": model_action, "model_sha256": manifest["model_sha256"],
              "model_trained_at": manifest["trained_at"], "current_data_fingerprint": fingerprint,
              "total_feature_rows": len(dataset), "verified_symbols": int((inventory.status == "CURRENT").sum()),
              "metadata": metadata, "prospective": prospective, "decision_context": context,
              "research_as_of": research.get("as_of"), "metrics": research.get("metrics", {}),
              "execution_research": research.get("execution_research", {}),
              "reasons": research.get("reasons", ["Full historical research has not been run for this model version"]),
              "limitations": ["Daily forecasts remain research-only.", "Quote snapshots may be delayed; use their timestamps.",
                              "Full historical metrics are dated separately and are not recomputed on every daily run."]}
    write_json(config.output_dir / "report.json", report)
    lines = ["# Daily Prediction Report", "", f"Data session: {report['as_of']}",
             f"Status: {report['status']}; action: {context['action']}; trading enabled: false",
             f"Model: {report['model']}; model action: {model_action}; trained at: {manifest['trained_at']}",
             f"Next modeled entry open: {context['next_entry_open']}",
             f"Historical study as of: {research.get('as_of', 'not available for this model')}",
             f"Prospective evidence: {prospective['evidence_status']}; mature eligible dates: {prospective['eligible_dates']}",
             "Prospective accuracy is N/A until eligible outcomes mature; see prospective_report.md for per-model scores.", "",
             "| Symbol | Probability | Signal date | Indicative price | Quote time | Quote status |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in latest.head(10).itertuples():
        price = "N/A" if pd.isna(row.price) else f"{row.price:.2f}"
        stamp = "N/A" if pd.isna(row.quote_at) else str(row.quote_at)
        quote_status = "NOT_REQUESTED" if pd.isna(row.quote_status) else str(row.quote_status)
        lines.append(f"| {row.symbol} | {row.probability:.2%} | {as_of.date()} | {price} | {stamp} | {quote_status} |")
    lines += ["", "Completed daily bars drive the model. Indicative quotes do not replace the model's daily features.",
              "WAIT_FOR_NEXT_CLOSE means the modeled next-open entry time has passed.",
              "Full research: python prediction_main.py --research --refresh"]
    (config.output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[RESULT] DAILY {report['status']}: model={model_action}; action={context['action']}", flush=True)
    return report


def record_forecast(latest: pd.DataFrame, config: PredictionConfig, metadata: dict, as_of) -> None:
    """Keep the first issued forecast each day; reruns cannot rewrite its history."""
    path = config.output_dir / "issued" / f"{as_of.date()}.json"
    if latest.empty or path.exists():
        return
    write_json(path, {"issued_at": pd.Timestamp.now("UTC").isoformat(), "as_of": str(as_of.date()),
                      "horizon": config.horizon, "cost_bps": config.cost_bps,
                      "execution_research": EXECUTION_PROTOCOL,
                      "model_sha256": file_hash(config.output_dir / "model.joblib"),
                      "metadata": metadata,
                      "predictions": latest[["symbol", "probability"]].to_dict("records")})


def evaluate_issued(dataset: pd.DataFrame, config: PredictionConfig) -> dict:
    from .prediction_prospective import evaluate_prospective

    return evaluate_prospective(dataset, config)


def run_prediction(config: PredictionConfig | None = None, *, refresh=False, max_downloads=60, daily=False, retrain=False) -> dict:
    config = config or PredictionConfig()
    with prediction_lock(config.output_dir):
        status_path = config.output_dir / "status.json"
        write_json(status_path, {"status": "RUNNING", "updated_at": pd.Timestamp.now("UTC").isoformat(), "trading_enabled": False})
        try:
            report = _run(config, refresh, max_downloads, daily=daily, retrain=retrain)
            write_json(status_path, report)
            return report
        except Exception as exc:
            write_json(status_path, {"status": "ERROR", "updated_at": pd.Timestamp.now("UTC").isoformat(),
                                     "error": f"{type(exc).__name__}: {exc}", "trading_enabled": False})
            raise


def _run(config, refresh, max_downloads, *, daily=False, retrain=False):
    as_of = completed_session()
    store = PredictionDataStore(config)
    frames, inventory = store.load(refresh=refresh, max_downloads=max_downloads, as_of=as_of)
    write_frame(config.output_dir / "data_inventory.csv", inventory)
    dataset = build_dataset(frames, config)
    parts = time_partitions(dataset, config)
    data_fingerprint = hashlib.sha256(json.dumps(inventory[["symbol", "sha256"]].to_dict("records"), sort_keys=True).encode()).hexdigest()
    model, metadata, manifest, model_action = _fit_or_load(parts, config, data_fingerprint, retrain=retrain)
    name, threshold, prior = metadata["selected_model"], metadata["threshold"], manifest["prior"]
    if daily:
        return _daily_report(dataset, inventory, model, metadata, manifest, model_action, config, store, as_of, refresh)
    metrics, all_blocks, reliability, reasons = {}, [], [], []
    execution_summaries, execution_curves, execution_trades, execution_errors = [], [], [], []
    execution_starts = []
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
        lower = {"validation": config.train_end, "test": config.validation_end, "forward": config.test_end}[part_name]
        upper = pd.Timestamp({"validation": config.validation_end, "test": config.test_end}.get(part_name, as_of))
        execution_data = dataset.loc[(dataset.date > pd.Timestamp(lower)) & (dataset.date <= upper)
                                     & (dataset.label_end <= upper)].copy()
        with threadpool_limits(limits=2):
            execution_data["probability"] = model.predict_proba(execution_data[FEATURES])[:, 1]
        try:
            summary, curve, trades = compare_execution(execution_data, frames, threshold, config)
            starts = execution_sensitivity(execution_data, frames, threshold, config)
            execution_summaries.append(summary.assign(partition=part_name))
            execution_curves.append(curve.assign(partition=part_name))
            execution_trades.append(trades.assign(partition=part_name))
            execution_starts.append(starts.assign(partition=part_name))
        except PortfolioDataError as exc:
            execution_errors.append(f"{part_name}: {exc}")
            reasons.append(f"{part_name}: constrained execution data failed validation")
    latest, data_ready, context = _latest_state(dataset, inventory, model, threshold, config, as_of)
    if not data_ready:
        reasons.append("One or more symbols have missing/stale verified history")
    if latest.empty:
        reasons.append("No predictions for latest completed session")
    write_frame(config.output_dir / "latest_predictions.csv", latest)
    write_frame(config.output_dir / "portfolio_blocks.csv", pd.concat(all_blocks, ignore_index=True))
    write_frame(config.output_dir / "probability_reliability.csv", pd.DataFrame(reliability))
    execution_summary = pd.concat(execution_summaries, ignore_index=True) if execution_summaries else pd.DataFrame()
    write_frame(config.output_dir / "execution_summary.csv", execution_summary)
    write_frame(config.output_dir / "execution_equity.csv", pd.concat(execution_curves, ignore_index=True) if execution_curves else pd.DataFrame())
    write_frame(config.output_dir / "execution_trades.csv", pd.concat(execution_trades, ignore_index=True) if execution_trades else pd.DataFrame())
    start_sensitivity = pd.concat(execution_starts, ignore_index=True) if execution_starts else pd.DataFrame()
    write_frame(config.output_dir / "execution_start_sensitivity.csv", start_sensitivity)
    write_json(config.output_dir / "execution_protocol.json", {**EXECUTION_PROTOCOL, "horizon": config.horizon,
                                                               "max_positions": config.top_k, "threshold": threshold})
    if data_ready:
        record_forecast(latest, config, metadata, as_of)
    prospective = evaluate_issued(dataset, config)
    report = {"status": "RESEARCH_PASS" if not reasons else "RESEARCH_ONLY", "trading_enabled": False,
              "mode": "RESEARCH", "model_action": model_action, "model_sha256": manifest["model_sha256"],
              "model_trained_at": manifest["trained_at"], "decision_context": context,
              "current_data_fingerprint": data_fingerprint,
              "updated_at": pd.Timestamp.now("UTC").isoformat(), "as_of": str(as_of.date()),
              "model": name, "threshold": threshold, "data_ready": data_ready,
              "total_feature_rows": len(dataset), "verified_symbols": len(frames),
              "split_dates": {key: {"first": str(value.date.min().date()), "last": str(value.date.max().date()),
                                    "last_label": str(value.label_end.max().date()), "rows": len(value)}
                              for key, value in parts.items() if not value.empty},
              "metrics": metrics, "reasons": reasons, "metadata": metadata, "prospective": prospective,
              "execution_research": {"protocol": EXECUTION_PROTOCOL,
                                     "results": json.loads(execution_summary.to_json(orient="records")),
                                     "starting_offsets": json.loads(start_sensitivity.to_json(orient="records")),
                                     "errors": execution_errors},
              "limitations": ["Current configured universe has survivorship bias; delisted stocks are not represented.",
                              "Only causal adjusted OHLCV features; latest SEC/FRED snapshots are deliberately excluded.",
                              "Fixed historical study, not a live validated or continuously refitted trading model.",
                              "The forward partition is retrospective 2026 data, not previously issued live predictions.",
                              "Block confidence interval is exploratory and does not eliminate regime dependence.",
                              "Raw model probabilities require forward monitoring; no guarantee of calibration."]}
    write_json(config.output_dir / "report.json", report)
    write_json(config.output_dir / "research_report.json", report)
    lines = ["# Prediction Research Report", "", f"Status: {report['status']}; trading enabled: false",
             f"As of: {report['as_of']}; model: {name}; research threshold: {threshold:.2f}",
             f"Verified symbols: {len(frames)}; feature rows: {len(dataset)}", "",
             "Signals use completed-session features; simulated entry is the next open, exit five sessions later by default.",
             "Position slots not selected remain cash. Model and threshold selection use validation data only.", "",
             f"Actually issued forecast days: {prospective['issued_days']}; mature prospective dates: {prospective['eligible_dates']}.",
             "The forward table below is retrospective; it is not evidence of live prediction performance.", "",
             "## Evaluation", "", "| Period | Brier | Prior baseline | Net return | SPY | Universe | Drawdown | Trade win rate | Trades |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for period, values in metrics.items():
        win_rate = f"{values['trade_win_rate']:.2%}" if values['trade_win_rate'] is not None else "N/A"
        lines.append(f"| {period} | {values['brier']:.4f} | {values['baseline_brier']:.4f} | {values['total_return']:.2%} | {values['spy_total_return']:.2%} | {values['universe_total_return']:.2%} | {values['max_drawdown']:.2%} | {win_rate} | {values['trades']} |")
    lines += ["", "## Gate Results", ""] + [f"- {reason}" for reason in reasons or ["Research checks passed; forward paper validation still required."]]
    lines += ["", "## Constrained Execution Research", "",
              "Both modes start with the same capital. Staggered books start equally funded; no borrowing or concurrent duplicate symbols.",
              "At most top_k names; entry spending per name is capped at equity/top_k. Existing weights can drift with prices.",
              "Fees are charged on each actual buy/sell; stress doubles them. Drawdown uses daily adjusted opens, not intraday extremes.",
              "Model probabilities and threshold are unchanged. These are exploratory results on previously inspected periods.", "",
              "| Period | Execution | Net return | Cost stress | Daily-open drawdown | Trade win rate | Trades | Max names |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in execution_summary.to_dict("records"):
        win_rate = "N/A" if pd.isna(row["trade_win_rate"]) else f"{row['trade_win_rate']:.2%}"
        lines.append(f"| {row['partition']} | {row['mode']} | {row['total_return']:.2%} | {row['stress_total_return']:.2%} | {row['max_drawdown']:.2%} | {win_rate} | {row['trades']} | {row['max_positions']} |")
    lines += [f"- Data validation error: {error}" for error in execution_errors]
    if not start_sensitivity.empty:
        lines += ["", "All starting offsets are retained; no favorable offset is selected.", "",
                  "| Period | Execution | Starting-date net return range | Starting-date win rate range |",
                  "| --- | --- | --- | --- |"]
        for (period, mode), group in start_sensitivity.groupby(["partition", "mode"], sort=False):
            win_range = "N/A" if group.trade_win_rate.isna().all() else f"{group.trade_win_rate.min():.2%} to {group.trade_win_rate.max():.2%}"
            lines.append(f"| {period} | {mode} | {group.total_return.min():.2%} to {group.total_return.max():.2%} | {win_range} |")
    lines += ["", "## Limitations", ""] + [f"- {item}" for item in report["limitations"]]
    (config.output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (config.output_dir / "research_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[RESULT] {report['status']}: {len(frames)} symbols, {len(dataset)} feature rows; trading disabled", flush=True)
    return report
