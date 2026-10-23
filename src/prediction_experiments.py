"""Registered development experiments with opt-in input refresh and no order path."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from importlib import metadata
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

from .prediction import (_training_code_fingerprint, block_metrics, portfolio_blocks,
                         prediction_lock, probability_metrics, write_frame)
from .prediction_data import PredictionConfig, PredictionDataStore, file_hash, write_json
from .prediction_experiment_features import ENRICHED_FEATURES, build_experiment_dataset
from .prediction_features import FEATURES, build_dataset
from .prediction_volatility import CboeHistoryStore, COMBINED_FEATURES, build_volatility_dataset


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def load_protocol(path):
    protocol = json.loads(Path(path).read_text(encoding="utf-8"))
    years = protocol["evaluation_years"]
    ceiling = pd.Timestamp(protocol["development_end"])
    names = [item["name"] for item in protocol["candidates"]]
    if (not years or years != sorted(set(years)) or max(years) > 2023
            or ceiling > pd.Timestamp("2023-12-31") or ceiling.year != max(years)):
        raise ValueError("Development experiments must exclude 2024 and later observations")
    rounds = protocol.get("rounds", [1, 2, 3])
    if (not rounds or rounds != sorted(set(rounds)) or any(type(number) is not int or number < 1 for number in rounds)
            or len(set(names)) != len(names) or set(item["round"] for item in protocol["candidates"]) != set(rounds)):
        raise ValueError("Require uniquely named candidates in all declared rounds")
    if not .5 <= protocol["threshold"] < 1 or protocol["calibration_dates"] < 2:
        raise ValueError("Invalid fixed threshold or calibration window")
    data_inputs = protocol.get("data_inputs", "ohlcv")
    if data_inputs not in {"ohlcv", "ohlcv_core", "cboe_volatility"}:
        raise ValueError("Unsupported data inputs")
    feature_sets = {"ohlcv": {"core", "enriched"}, "ohlcv_core": {"core"},
                    "cboe_volatility": {"core", "volatility"}}[data_inputs]
    if ("minimum_symbol_prior_brier_skill_each_year" in protocol["gates"]
            and not protocol.get("symbol_prior_comparison")):
        raise ValueError("Stock-prior gate requires the registered comparison")
    for candidate in protocol["candidates"]:
        if (candidate["model"] not in {"logistic", "symbol_logistic", "hist_gradient", "lightgbm"}
                or candidate["features"] not in feature_sets
                or (candidate["model"] == "symbol_logistic" and candidate["features"] != "core")
                or (candidate["calibrated"] and not candidate["recent"])):
            raise ValueError("Unsupported candidate definition")
    return protocol


def development_folds(dataset, protocol):
    ceiling = pd.Timestamp(protocol["development_end"])
    data = dataset.loc[(dataset.date <= ceiling) & (dataset.label_end <= ceiling)].dropna(
        subset=["target", "gross_return", "spy_return", "entry_date", "label_end"])
    if "complete_outcomes" in data:
        data = data.loc[data.complete_outcomes]
    for year in protocol["evaluation_years"]:
        start, end = pd.Timestamp(year, 1, 1), min(pd.Timestamp(year, 12, 31), ceiling)
        train = data.loc[(data.date < start) & (data.label_end < start)].copy()
        evaluate = data.loc[(data.date >= start) & (data.date <= end) & (data.label_end <= end)].copy()
        if (train.date.nunique() < protocol["minimum_fit_dates"]
                or evaluate.date.nunique() < protocol["minimum_evaluation_dates"]
                or train.symbol.nunique() < protocol["minimum_symbols"]
                or evaluate.symbol.nunique() < protocol["minimum_symbols"]
                or train.target.nunique() != 2):
            raise ValueError(f"Insufficient common support for development year {year}")
        yield year, train, evaluate


def fitting_segments(train, year, candidate, protocol):
    if not candidate["recent"]:
        return train, train.iloc[:0]
    start = pd.Timestamp(year, 1, 1) - pd.DateOffset(years=protocol["recent_years"])
    recent = train.loc[train.date >= start]
    dates = sorted(recent.date.unique())
    count = protocol["calibration_dates"]
    if len(dates) <= count:
        raise ValueError("Insufficient recent dates for reserved calibration")
    calibration_start = dates[-count]
    fit = recent.loc[(recent.date < calibration_start) & (recent.label_end < calibration_start)]
    calibration = recent.loc[recent.date >= calibration_start]
    if fit.date.nunique() < protocol["minimum_fit_dates"] or fit.target.nunique() != 2:
        raise ValueError("Insufficient purged training data after reserving calibration")
    return fit, calibration


def make_model(name, protocol):
    parameters = protocol["models"][name]
    if name == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(**parameters))
    if name == "symbol_logistic":
        encoding = ColumnTransformer([
            ("numeric", StandardScaler(), FEATURES),
            ("stock", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["symbol"]),
        ])
        return make_pipeline(encoding, LogisticRegression(**parameters))
    if name == "hist_gradient":
        return HistGradientBoostingClassifier(**parameters)
    from lightgbm import LGBMClassifier

    return LGBMClassifier(**parameters)


def checked_probabilities(values, length):
    values = np.asarray(values, dtype=float)
    if values.shape != (length,) or not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("Invalid model probabilities")
    return values


def log_odds(probabilities):
    clipped = np.clip(probabilities, 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def calibrate(probabilities, targets, evaluate_probability, protocol):
    if pd.Series(targets).nunique() != 2:
        raise ValueError("Calibration requires two target classes")
    calibrator = LogisticRegression(**protocol["models"]["sigmoid"])
    calibrator.fit(log_odds(probabilities), np.asarray(targets, dtype=int))
    if calibrator.coef_[0, 0] <= 0:
        raise ValueError("Calibration is not monotonically increasing; candidate rejected")
    return calibrator.predict_proba(log_odds(evaluate_probability))[:, 1]


def score_candidate(evaluate, probabilities, prior, config, threshold, *, symbol_priors=None):
    values = checked_probabilities(probabilities, len(evaluate))
    scored = evaluate.assign(probability=values)
    selected = scored.loc[scored.probability >= threshold]
    metrics = probability_metrics(scored, values, prior)
    metrics.update({
        "brier_skill": 1 - metrics["brier"] / metrics["baseline_brier"],
        "classification_accuracy": float(((values >= .5) == scored.target).mean()),
        "always_positive_accuracy": float(scored.target.mean()),
        "signal_count": len(selected), "signal_coverage": len(selected) / len(scored),
        "signal_hit_rate": float(selected.target.mean()) if len(selected) else None,
    })
    if symbol_priors is not None:
        stock_baseline = scored.symbol.map(symbol_priors).fillna(prior).to_numpy(dtype=float)
        checked_probabilities(stock_baseline, len(scored))
        stock_brier = float(((stock_baseline - scored.target.to_numpy()) ** 2).mean())
        metrics.update(symbol_prior_brier=stock_brier,
                       symbol_prior_brier_skill=1 - metrics["brier"] / stock_brier if stock_brier > 0 else None,
                       symbol_prior_unseen_rows=int((~scored.symbol.isin(symbol_priors)).sum()))
    dates = sorted(scored.date.unique())
    phases = []
    for offset in range(min(config.horizon, len(dates))):
        blocks = portfolio_blocks(scored.loc[scored.date >= dates[offset]], threshold, config)
        phases.append({"phase": offset, **block_metrics(blocks, config)})
    reliability = []
    for bin_number in range(10):
        group = scored.loc[(scored.probability >= bin_number / 10)
                           & ((scored.probability < (bin_number + 1) / 10) if bin_number < 9 else (scored.probability <= 1))]
        reliability.append({"bin": bin_number, "count": len(group),
                            "mean_probability": float(group.probability.mean()) if len(group) else None,
                            "hit_rate": float(group.target.mean()) if len(group) else None})
    return clean({"metrics": metrics, "starting_phases": phases, "reliability": reliability})


def summarize(results, protocol):
    summaries, gates = [], protocol["gates"]
    for candidate in protocol["candidates"]:
        folds = [row for row in results if row["candidate"] == candidate["name"]]
        successful = [row for row in folds if row["status"] == "COMPLETE"]
        failures = []
        if sorted(row["year"] for row in successful) != protocol["evaluation_years"]:
            failures.append("incomplete_or_failed_folds")
        if any(sorted(phase["phase"] for phase in row["starting_phases"]) != list(range(protocol["horizon"]))
               for row in successful):
            failures.append("incomplete_starting_phases")
        phases = [phase for row in successful for phase in row["starting_phases"]]
        if any(row["metrics"]["brier_skill"] <= gates["minimum_brier_skill_each_year"] for row in successful):
            failures.append("probability_baseline_not_beaten_every_year")
        stock_gate = gates.get("minimum_symbol_prior_brier_skill_each_year")
        if stock_gate is not None and any(row["metrics"].get("symbol_prior_brier_skill") is None
                                         or row["metrics"]["symbol_prior_brier_skill"] <= stock_gate for row in successful):
            failures.append("stock_prior_baseline_not_beaten_every_year")
        if any(row["trades"] < gates["minimum_trades_per_year_phase"]
               or row["active_blocks"] < gates["minimum_active_blocks_per_year_phase"] for row in phases):
            failures.append("insufficient_trade_coverage_in_year_or_phase")
        if any(row["stress_total_return"] <= gates["minimum_stress_return_each_year_phase"] for row in phases):
            failures.append("cost_stress_failed_in_year_or_phase")
        if any(row["max_drawdown"] < gates["maximum_drawdown"] for row in phases):
            failures.append("drawdown_limit_failed_in_year_or_phase")
        summaries.append({"candidate": candidate["name"], "round": candidate["round"],
                          "completed_folds": len(successful), "failed_folds": len(folds) - len(successful),
                          "status": "REJECTED_DEVELOPMENT" if failures else "DEVELOPMENT_ONLY_SHADOW_REVIEW",
                          "reasons": failures,
                          "worst_year_brier_skill": min((row["metrics"]["brier_skill"] for row in successful), default=None),
                          "worst_year_symbol_prior_brier_skill": min((row["metrics"]["symbol_prior_brier_skill"]
                              for row in successful if row["metrics"].get("symbol_prior_brier_skill") is not None), default=None),
                          "worst_year_phase_stress_return": min((row["stress_total_return"] for row in phases), default=None),
                          "worst_year_phase_drawdown": min((row["max_drawdown"] for row in phases), default=None),
                          "minimum_year_phase_trades": min((row["trades"] for row in phases), default=0),
                          "minimum_year_phase_active_blocks": min((row["active_blocks"] for row in phases), default=0),
                          "policy_changed": False, "trading_enabled": False})
    return clean(summaries)


def freeze_registration(directory, registration):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "registration.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if any(existing.get(key) != registration.get(key) for key in
               ("input_key", "protocol", "data_sha256", "versions", "sources", "symbols")):
            raise ValueError("Registration identity changed; refusing to overwrite")
        return existing
    write_json(path, registration)
    return registration


def completed_report(directory, key):
    path = directory / "completion.json"
    if not path.exists():
        return None
    completion = json.loads(path.read_text(encoding="utf-8"))
    if completion["input_key"] != key:
        raise ValueError("Experiment completion identity mismatch")
    for name, expected in completion["files"].items():
        if Path(name).name != name or file_hash(directory / name) != expected:
            raise ValueError("Experiment evidence checksum mismatch; refusing silent rerun")
    return json.loads((directory / "report.json").read_text(encoding="utf-8"))


def _render_report(report):
    def percent(value):
        return "N/A" if value is None else f"{value:.2%}"

    lines = ["# Registered Prediction Experiments", "", f"Input key: {report['input_key']}",
             "Development years only: 2018-2023. No test/forward optimization, promotion, or trading.",
             f"{len(report['candidates'])} fixed candidates, one seed, fixed {report['threshold']} threshold, and all {report['horizon']} starting phases.", "",
             "## Cross-Year Gates", "",
             "| Round | Candidate | Complete folds | Worst Brier skill | Worst stock-prior skill | Worst stress return | Minimum trades | Decision |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["candidates"]:
        lines.append(f"| {row['round']} | {row['candidate']} | {row['completed_folds']} | "
                     f"{percent(row['worst_year_brier_skill'])} | {percent(row['worst_year_symbol_prior_brier_skill'])} | {percent(row['worst_year_phase_stress_return'])} | "
                     f"{row['minimum_year_phase_trades']} | {row['status']} |")
    lines += ["", "Returns above are the WORST year/phase, not a recommended portfolio or a compound multi-year return.",
              "Brier skill compares with each fit window's fixed target-frequency probability, not a hindsight prior.", "",
              "## Annual Diagnostics (All Phases Retained Separately)", "",
              "| Candidate | Year | Brier skill | Stock-prior skill | AUC | Signal hit rate | Coverage | Outcome |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["folds"]:
        metrics = row.get("metrics", {})
        auc = "N/A" if metrics.get("auc") is None else f"{metrics['auc']:.3f}"
        lines.append(f"| {row['candidate']} | {row['year']} | {percent(metrics.get('brier_skill'))} | {percent(metrics.get('symbol_prior_brier_skill'))} | {auc} | "
                     f"{percent(metrics.get('signal_hit_rate'))} | {percent(metrics.get('signal_coverage'))} | {row['status']} |")
    lines += ["", "## Rejection Reasons", ""]
    for row in report["candidates"]:
        lines.append(f"- {row['candidate']}: {', '.join(row['reasons']) or 'Development gates only; needs new prospective confirmation.'}")
    for row in report["folds"]:
        if row["status"] == "FAILED":
            lines.append(f"- {row['candidate']} {row['year']}: {row['error']}")
    lines += ["", "## Limitations", "", *[f"- {item}" for item in report["limitations"]]]
    return "\n".join(lines) + "\n"


def run_experiments(protocol_path=Path("config/prediction_experiment_v1.json"),
                    output_dir=Path("outputs/prediction/experiments"), *, refresh_inputs=False):
    protocol = load_protocol(protocol_path)
    base = PredictionConfig()
    config = replace(base, horizon=protocol["horizon"], top_k=protocol["top_k"],
                     cost_bps=protocol["cost_bps"], seed=protocol["seed"])
    with prediction_lock(Path(output_dir)):
        store, frames, inventory = PredictionDataStore(config), {}, []
        input_hash = hashlib.sha256()
        for symbol in dict.fromkeys(("SPY", *config.symbols)):
            frame, info = store.read(symbol)
            if file_hash(config.cache_dir / f"{symbol}.csv") != info["sha256"]:
                raise ValueError("Cache changed during snapshot; try after daily update finishes")
            frame = frame.loc[(frame.index >= config.start) & (frame.index <= protocol["development_end"])].copy()
            if frame.empty:
                raise ValueError(f"No development history for {symbol}")
            input_hash.update(symbol.encode())
            input_hash.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
            frames[symbol] = frame
            inventory.append({"symbol": symbol, "source_sha256": info["sha256"], "rows": len(frame),
                              "first": str(frame.index.min().date()), "last": str(frame.index.max().date())})
        histories, external_inventory = {}, []
        if protocol.get("data_inputs") == "cboe_volatility":
            loaded, external_inventory = CboeHistoryStore().load(refresh=refresh_inputs)
            for name, frame in loaded.items():
                frame = frame.loc[(frame.index >= config.start) & (frame.index <= protocol["development_end"])].copy()
                if frame.empty:
                    raise ValueError(f"No development history for {name}")
                histories[name] = frame
                input_hash.update(name.encode())
                input_hash.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
        versions = {}
        for name in ("numpy", "pandas", "scikit-learn", "scipy", "lightgbm"):
            try:
                versions[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                versions[name] = "NOT_INSTALLED"
        sources = {name: file_hash(Path(__file__).with_name(name)) for name in
                   ("prediction_experiments.py", "prediction_experiment_features.py", "prediction_features.py")}
        sources["shared_training_functions"] = _training_code_fingerprint()
        if histories:
            sources["prediction_volatility.py"] = file_hash(Path(__file__).with_name("prediction_volatility.py"))
        identity = {"protocol": protocol, "data_sha256": input_hash.hexdigest(), "versions": versions,
                    "sources": sources, "symbols": list(config.symbols)}
        key = digest_json(identity)
        directory = Path(output_dir) / key
        registration = freeze_registration(directory, {
            "input_key": key, **identity, "registered_at": pd.Timestamp.now("UTC").isoformat(),
            "cache_snapshot": inventory, "external_snapshot": external_inventory,
            "policy_changed": False, "trading_enabled": False})
        previous = completed_report(directory, key)
        if previous is not None:
            print("[EXPERIMENT] Verified existing evidence; identical inputs not refitted", flush=True)
            return previous
        print(f"[EXPERIMENT] Protocol and inputs frozen before fitting: {key}", flush=True)
        if protocol.get("data_inputs") == "ohlcv_core":
            dataset = build_dataset(frames, config)
            coverage = {"core_rows": len(dataset), "common_rows": len(dataset), "feature_rows_excluded": 0,
                        "core_features": len(FEATURES), "categorical_input": "symbol, fitted within each training fold"}
        else:
            dataset, coverage = (build_volatility_dataset(frames, histories, config) if histories
                                 else build_experiment_dataset(frames, config))
        results, files = [], []
        for year, train, evaluate in development_folds(dataset, protocol):
            fitted = {}
            for candidate in protocol["candidates"]:
                name = candidate["name"]
                result_path = directory / f"{name}-{year}.json"
                if result_path.exists():
                    row = json.loads(result_path.read_text(encoding="utf-8"))
                    checksum = row.pop("result_sha256", None)
                    if checksum != digest_json(row):
                        raise ValueError("Saved fold checksum mismatch; refusing silent rerun")
                    row["result_sha256"] = checksum
                    if row.get("input_key") != key or row.get("candidate") != name or row.get("year") != year:
                        raise ValueError("Saved fold identity mismatch")
                    results.append(row)
                    files.append(result_path.name)
                    continue
                print(f"[ROUND {candidate['round']}] {name}: {year}", flush=True)
                row = {"input_key": key, "candidate": name, "round": candidate["round"], "year": year,
                       "status": "FAILED", "started_at": pd.Timestamp.now("UTC").isoformat()}
                started = time.monotonic()
                try:
                    fit, calibration = fitting_segments(train, year, candidate, protocol)
                    columns = {"core": FEATURES, "enriched": ENRICHED_FEATURES,
                               "volatility": COMBINED_FEATURES}[candidate["features"]]
                    if candidate["model"] == "symbol_logistic":
                        columns = [*columns, "symbol"]
                    fit_key = (candidate["model"], candidate["features"], candidate["recent"])
                    with threadpool_limits(limits=2):
                        if fit_key not in fitted:
                            model = make_model(candidate["model"], protocol)
                            model.fit(fit[columns], fit.target.astype(int))
                            fitted[fit_key] = model
                        model = fitted[fit_key]
                        probability = checked_probabilities(model.predict_proba(evaluate[columns])[:, 1], len(evaluate))
                        if candidate["calibrated"]:
                            calibration_probability = checked_probabilities(
                                model.predict_proba(calibration[columns])[:, 1], len(calibration))
                            probability = calibrate(calibration_probability, calibration.target, probability, protocol)
                    stock_priors = fit.groupby("symbol").target.mean().to_dict() if protocol.get("symbol_prior_comparison") else None
                    row.update(score_candidate(evaluate, probability, float(fit.target.mean()),
                                               config, protocol["threshold"], symbol_priors=stock_priors))
                    row.update(status="COMPLETE", training_rows=len(fit), features=len(columns),
                               training_first=str(fit.date.min().date()), training_last_label=str(fit.label_end.max().date()),
                               calibration_dates=calibration.date.nunique(),
                               calibration_first=str(calibration.date.min().date()) if len(calibration) else None,
                               calibration_last_label=str(calibration.label_end.max().date()) if len(calibration) else None,
                               evaluation_first=str(evaluate.date.min().date()), evaluation_last_label=str(evaluate.label_end.max().date()))
                except Exception as exc:
                    row.update(error=f"{type(exc).__name__}: {exc}")
                    print(f"[EXPERIMENT] Failed candidate retained: {name} {year}: {type(exc).__name__}", flush=True)
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                row = clean(row)
                row["result_sha256"] = digest_json(row)
                write_json(result_path, clean(row))
                results.append(clean(row))
                files.append(result_path.name)
        summaries = summarize(results, protocol)
        report = {"input_key": key, "status": "COMPLETE" if all(row["status"] == "COMPLETE" for row in results) else "COMPLETE_WITH_FAILURES",
                  "registered_at": registration["registered_at"], "completed_at": pd.Timestamp.now("UTC").isoformat(),
                  "report_path": str((directory / "report.md").resolve()), "coverage": coverage,
                  "development_end": protocol["development_end"], "threshold": protocol["threshold"],
                  "horizon": protocol["horizon"], "candidates": summaries, "folds": results,
                  "policy_changed": False, "trading_enabled": False, "limitations": protocol["limitations"]}
        write_json(directory / "report.json", report)
        (directory / "report.md").write_text(_render_report(report), encoding="utf-8")
        write_frame(directory / "summary.csv", pd.DataFrame(summaries))
        phase_rows = [{"candidate": row["candidate"], "year": row["year"], **phase}
                      for row in results for phase in row.get("starting_phases", [])]
        write_frame(directory / "starting_phases.csv", pd.DataFrame(phase_rows))
        files += ["registration.json", "report.json", "report.md", "summary.csv", "starting_phases.csv"]
        write_json(directory / "completion.json", {"input_key": key, "files": {name: file_hash(directory / name) for name in files}})
        write_json(Path(output_dir) / "latest.json", {"input_key": key, "report_path": report["report_path"],
                                                   "status": report["status"], "policy_changed": False, "trading_enabled": False})
        return report
