"""Offline hit-rate diagnostics; never promotes a model or changes its threshold."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd
from threadpoolctl import threadpool_limits

from .prediction import (block_metrics, candidate_models, portfolio_blocks, prediction_lock,
                         probability_metrics, write_frame)
from .prediction_data import PredictionConfig, PredictionDataStore, write_json
from .prediction_features import FEATURES, build_dataset, time_partitions


def hit_metrics(scored: pd.DataFrame, threshold: float, config: PredictionConfig) -> dict:
    selected = scored.loc[scored.probability >= threshold]
    return {
        "rows": len(scored), "dates": scored.date.nunique(),
        "classification_accuracy": float(((scored.probability >= .5) == scored.target).mean()),
        "always_positive_accuracy": float(scored.target.mean()),
        "signal_count": len(selected), "signal_coverage": len(selected) / len(scored),
        "signal_hit_rate": float(selected.target.mean()) if len(selected) else None,
        "signal_mean_probability": float(selected.probability.mean()) if len(selected) else None,
        **block_metrics(portfolio_blocks(scored, threshold, config), config),
    }


def validation_folds(dataset: pd.DataFrame, config: PredictionConfig, window_years: int | None):
    """Only development years are exposed; purge every label crossing a fold boundary."""
    ceiling = pd.Timestamp(config.validation_end)
    labeled = dataset.dropna(subset=["target", "gross_return", "spy_return", "label_end"])
    labeled = labeled.loc[(labeled.date <= ceiling) & (labeled.label_end <= ceiling)]
    for year in range(pd.Timestamp(config.train_end).year + 1, ceiling.year + 1):
        start = pd.Timestamp(year=year, month=1, day=1)
        end = min(pd.Timestamp(year=year, month=12, day=31), ceiling)
        fit = labeled.loc[(labeled.date < start) & (labeled.label_end < start)]
        if window_years is not None:
            fit = fit.loc[fit.date >= start - pd.DateOffset(years=window_years)]
        evaluate = labeled.loc[(labeled.date >= start) & (labeled.date <= end) & (labeled.label_end <= end)]
        if (fit.date.nunique() < config.min_train_dates or evaluate.date.nunique() < config.min_eval_dates
                or fit.target.nunique() < 2 or fit.symbol.nunique() < config.min_symbols):
            raise ValueError(f"Insufficient observations for annual audit fold {year}")
        yield year, fit, evaluate


def phase_audit(scored: pd.DataFrame, threshold: float, config: PredictionConfig) -> pd.DataFrame:
    """Report every starting phase, never select the most favorable phase."""
    dates = sorted(scored.date.unique())
    return pd.DataFrame([{"phase": offset, **hit_metrics(scored.loc[scored.date >= dates[offset]], threshold, config)}
                         for offset in range(min(config.horizon, len(dates)))])


def annual_refit_audit(dataset: pd.DataFrame, config: PredictionConfig, threshold: float) -> pd.DataFrame:
    rows = []
    for window in (None, 5, 10):
        for year, train, evaluate in validation_folds(dataset, config, window):
            name = f"annual_{window}y" if window else "annual_expanding"
            print(f"[AUDIT] {name}: validation year {year}", flush=True)
            model = candidate_models(config.seed)["logistic"]
            with threadpool_limits(limits=2):
                model.fit(train[FEATURES], train.target.astype(int))
                probabilities = model.predict_proba(evaluate[FEATURES])[:, 1]
            scored = evaluate.assign(probability=probabilities)
            rows.append({"candidate": name, "year": year, "threshold": threshold,
                         "training_first": str(train.date.min().date()),
                         "training_last_label": str(train.label_end.max().date()),
                         **probability_metrics(evaluate, probabilities, float(train.target.mean())),
                         **hit_metrics(scored, threshold, config)})
    return pd.DataFrame(rows)


def run_audit(output_dir: Path = Path("outputs/prediction")) -> dict:
    with prediction_lock(output_dir):
        report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
        settings = dict(report["metadata"]["config"])
        settings.update(symbols=tuple(settings["symbols"]), cache_dir=Path(settings["cache_dir"]), output_dir=output_dir)
        config = PredictionConfig(**settings)
        # This is the project's own artifact; never accept downloaded/untrusted joblib files.
        artifact = joblib.load(output_dir / "model.joblib")
        if json.dumps(artifact["metadata"], sort_keys=True) != json.dumps(report["metadata"], sort_keys=True):
            raise ValueError("Model and report do not match; rerun prediction first")
        frames, inventory = PredictionDataStore(config).load(as_of=report["as_of"])
        fingerprint = hashlib.sha256(json.dumps(inventory[["symbol", "sha256"]].to_dict("records"), sort_keys=True).encode()).hexdigest()
        if fingerprint != report.get("current_data_fingerprint", report["metadata"]["data_fingerprint"]):
            raise ValueError("Cache changed since the model run; rerun prediction before auditing")
        dataset = build_dataset(frames, config)
        parts = time_partitions(dataset, config)
        prior = float(parts["train"].target.mean())
        threshold = float(report["threshold"])
        rows, sensitivity, phases = [], [], []
        for partition in ("validation", "test", "forward"):
            data = parts[partition]
            if data.empty:
                continue
            with threadpool_limits(limits=2):
                probabilities = artifact["model"].predict_proba(data[FEATURES])[:, 1]
            scored = data.assign(probability=probabilities)
            phases.append(phase_audit(scored, threshold, config).assign(partition=partition))
            rows.append({"partition": partition, "threshold": threshold,
                         **probability_metrics(data, probabilities, prior), **hit_metrics(scored, threshold, config)})
            if partition == "validation":
                for cutoff in (.50, .55, .60, .65):
                    sensitivity.append({"threshold": cutoff, **hit_metrics(scored, cutoff, config)})
                for year, group in scored.groupby(scored.date.dt.year):
                    group = group.loc[group.label_end <= pd.Timestamp(year=year, month=12, day=31)]
                    rows.append({"partition": f"validation_{year}", "threshold": threshold,
                                 **probability_metrics(group, group.probability, prior), **hit_metrics(group, threshold, config)})
        baseline = pd.DataFrame(rows)
        annual = annual_refit_audit(dataset, config, threshold)
        directory = output_dir / "audit"
        directory.mkdir(exist_ok=True)
        write_frame(directory / "baseline.csv", baseline)
        write_frame(directory / "annual_refit_validation.csv", annual)
        write_frame(directory / "validation_thresholds.csv", pd.DataFrame(sensitivity))
        phase_results = pd.concat(phases, ignore_index=True)
        write_frame(directory / "starting_phases.csv", phase_results)
        result = {"as_of": report["as_of"], "data_fingerprint": fingerprint,
                  "policy_changed": False, "trading_enabled": False,
                  "baseline": json.loads(baseline.to_json(orient="records")),
                  "annual_refit_validation": json.loads(annual.to_json(orient="records")),
                  "starting_phases": json.loads(phase_results.to_json(orient="records")),
                  "limitations": ["Post-hoc exploratory diagnosis, not a fresh holdout experiment.",
                                  "Annual candidate comparisons use validation years only; no automatic promotion.",
                                  "Daily stock labels overlap; trade counts also cluster within market dates.",
                                  "Win rate alone ignores loss magnitude, costs and participation."]}
        write_json(directory / "report.json", result)
        lines = ["# Hit Rate Audit", "", f"Data as of {report['as_of']}. No policy changes or trading enabled.", "",
                 "A hit is a positive next-open-to-exit-open return AFTER round-trip costs.",
                 "Trade win rate includes only top-K positions in the original non-overlapping portfolio schedule.",
                 "Signal hit rate includes all threshold signals and overlapping dates; do not confuse these metrics.", "",
                 "## Frozen Model", "", "| Period | Trade win rate | Trades | Active blocks | AUC | Net return | Profit factor |",
                 "| --- | --- | --- | --- | --- | --- | --- |"]
        def percent(value):
            return "N/A" if pd.isna(value) else f"{value:.2%}"
        for row in baseline.to_dict("records"):
            factor = "N/A" if pd.isna(row["profit_factor"]) else f"{row['profit_factor']:.2f}"
            lines.append(f"| {row['partition']} | {percent(row['trade_win_rate'])} | {row['trades']} | {row['active_blocks']} | {row['auc']:.3f} | {percent(row['total_return'])} | {factor} |")
        lines += ["", "## Annual Refit: Validation Only", "",
                  "Fixed 0.55 default policy threshold (or original report threshold); identical features and logistic architecture.",
                  "These years have already been inspected. Apparent gains need new prospective validation.", "",
                  "| Candidate | Year | Trade win rate | Trades | AUC | Net return |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for row in annual.to_dict("records"):
            lines.append(f"| {row['candidate']} | {row['year']} | {percent(row['trade_win_rate'])} | {row['trades']} | {row['auc']:.3f} | {percent(row['total_return'])} |")
        lines += ["", "## Starting Phase Sensitivity", "",
                  "All possible offsets for the fixed holding horizon are reported, not ranked or selected.",
                  "This diagnoses dependence on the first rebalance day; it does not authorize choosing a favorable date.", "",
                  "| Period | Offset sessions | Trade win rate | Trades | Net return |",
                  "| --- | --- | --- | --- | --- |"]
        for row in phase_results.to_dict("records"):
            lines.append(f"| {row['partition']} | {row['phase']} | {percent(row['trade_win_rate'])} | {row['trades']} | {percent(row['total_return'])} |")
        lines += ["", "## Interpretation", "",
                  "Reject a higher hit rate when it comes from very few trades, worse payoff, or one favorable year.",
                  "Recent-window training is a hypothesis, not a guaranteed fix for regime change.",
                  "Calibration requires a separate chronological calibration segment; it cannot create ranking signal.",
                  "Future work should predeclare rolling folds, minimum trade coverage, costs and risk limits before seeing outcomes.",
                  "Existing test/2026 results are diagnostic only; this audit does not retune against them."]
        (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[AUDIT] Complete: {directory / 'report.md'}; policy unchanged", flush=True)
        return result
