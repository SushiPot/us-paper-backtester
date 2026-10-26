"""A registered frozen-model forward observation stream, separate from daily policy."""
from __future__ import annotations

import ast
from dataclasses import asdict, replace
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform

import joblib
import numpy as np
import pandas as pd

from .market_calendar import completed_session, get_us_market_session, now_new_york
from .prediction_data import PredictionConfig, file_hash, write_json
from .prediction_features import FEATURES


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "config/prediction_shadow_v1.json"
STUDY = "frozen-baseline-v1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _settings(config):
    values = {key: value for key, value in asdict(config).items()
              if key not in {"output_dir", "cache_dir", "request_interval"}}
    return json.loads(json.dumps(values))


def _sources():
    directory = Path(__file__).parent
    sources = {name: hashlib.sha256((directory / name).read_text(encoding="utf-8").encode()).hexdigest()
               for name in ("prediction_shadow.py", "prediction_data.py", "prediction_features.py", "prediction_prospective.py",
                            "prediction_outcome_archive.py", "market_calendar.py")}
    tree = ast.parse((directory / "prediction.py").read_text(encoding="utf-8"))
    rules = {node.name: ast.dump(node, include_attributes=False) for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in {"_latest_state", "record_forecast"}}
    if len(rules) != 2:
        raise ValueError("Missing frozen forecast implementation")
    sources["forecast_rules"] = _digest(rules)
    return sources


def _versions():
    versions = {"python": platform.python_version()}
    for name in ("numpy", "pandas", "scikit-learn", "scipy", "joblib", "pandas_market_calendars", "tzdata"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def _root(config):
    return config.output_dir / "shadow" / STUDY


def _protocol():
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _keep_bytes(path, content):
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Refusing to replace frozen artifact: {path.name}")
        return
    with path.open("xb") as handle:
        handle.write(content)


def _read_registration(root):
    record = json.loads((root / "registration.json").read_text(encoding="utf-8"))
    checksum = record.pop("registration_sha256")
    if checksum != _digest(record):
        raise ValueError("Shadow registration checksum mismatch")
    return record, checksum


def _load(root, config):
    registration, checksum = _read_registration(root)
    if (registration["protocol"] != _protocol() or registration["settings"] != _settings(config)
            or registration["sources"] != _sources() or registration["versions"] != _versions()):
        raise ValueError("Frozen shadow protocol, settings, code or environment changed")
    for name, expected in registration["files"].items():
        if Path(name).name != name or file_hash(root / name) != expected:
            raise ValueError("Frozen shadow artifact checksum mismatch")
    if set(registration["files"]) != {"model.joblib", "model_manifest.json"}:
        raise ValueError("Incomplete shadow artifact registration")
    artifact = joblib.load(root / "model.joblib")
    if json.loads(json.dumps(artifact["metadata"])) != registration["model_metadata"]:
        raise ValueError("Frozen model metadata differs from registration")
    return registration, checksum, artifact


def register_shadow(config: PredictionConfig | None = None):
    from .prediction import prediction_lock

    config = config or PredictionConfig()
    root = _root(config)
    with prediction_lock(config.output_dir), prediction_lock(root):
        if (root / "registration.json").exists():
            return _load(root, config)[0]
        model_path = config.output_dir / "model.joblib"
        manifest_path = config.output_dir / "model_manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        model_bytes = model_path.read_bytes()
        if hashlib.sha256(model_bytes).hexdigest() != manifest["model_sha256"]:
            raise ValueError("Current model checksum mismatch; cannot register shadow")
        artifact = joblib.load(model_path)
        model_metadata = json.loads(json.dumps(artifact["metadata"]))
        settings = {key: value for key, value in model_metadata["config"].items()
                    if key not in {"output_dir", "cache_dir", "request_interval"}}
        threshold = float(model_metadata["threshold"])
        if (settings != _settings(config) or model_metadata["features"] != FEATURES
                or model_metadata["training_key"] != manifest["input_key"]
                or not np.isfinite(threshold) or not 0 <= threshold <= 1):
            raise ValueError("Current model metadata does not match requested shadow policy")
        record = {"schema": 1, "protocol": _protocol(), "registered_at": pd.Timestamp.now("UTC").isoformat(),
                  "first_signal_session": str(completed_session().date()), "settings": settings,
                  "model_metadata": model_metadata, "sources": _sources(), "versions": _versions(),
                  "files": {"model.joblib": manifest["model_sha256"],
                            "model_manifest.json": hashlib.sha256(manifest_bytes).hexdigest()},
                  "trading_enabled": False, "policy_changed": False}
        _keep_bytes(root / "model.joblib", model_bytes)
        _keep_bytes(root / "model_manifest.json", manifest_bytes)
        write_json(root / "registration.json", {**record, "registration_sha256": _digest(record)})
        return record


def run_registered_shadow(dataset, inventory, config, as_of):
    from .prediction import _latest_state, prediction_lock, record_forecast, write_frame
    from .prediction_prospective import evaluate_prospective

    root = _root(config)
    if not (root / "registration.json").exists():
        status = "INCOMPLETE_REGISTRATION" if (root / "model.joblib").exists() else "NOT_REGISTERED"
        return {"status": status, "trading_enabled": False}
    try:
        with prediction_lock(root):
            registration, checksum, artifact = _load(root, config)
            shadow_config = replace(config, output_dir=root)
            model_metadata = artifact["metadata"]
            latest, ready, context = _latest_state(dataset, inventory, artifact["model"],
                                                   model_metadata["threshold"], shadow_config, as_of)
            now = pd.Timestamp(now_new_york())
            session = get_us_market_session(pd.Timestamp(as_of, tz="America/New_York").replace(hour=12).to_pydatetime())
            timely = (session.market_close is not None and now >= pd.Timestamp(session.market_close) + pd.Timedelta(minutes=30)
                      and now < pd.Timestamp(context["next_entry_open"])
                      and pd.Timestamp(as_of) >= pd.Timestamp(registration["first_signal_session"])
                      and now >= pd.Timestamp(registration["registered_at"]))
            if ready and timely:
                feature_rows = dataset.loc[dataset.date == as_of, ["symbol", *FEATURES]].sort_values("symbol")
                inputs = feature_rows.to_dict("records")
                if (feature_rows.symbol.duplicated().any() or set(feature_rows.symbol) != set(config.symbols)
                        or not np.isfinite(feature_rows[FEATURES].to_numpy()).all()
                        or not np.isfinite(latest.probability).all() or not latest.probability.between(0, 1).all()):
                    raise ValueError("Invalid shadow features, universe or probabilities")
                source_files = inventory[["symbol", "sha256", "status"]].sort_values("symbol").to_dict("records")
                forecast_metadata = {**model_metadata, "shadow": {"registration_sha256": checksum,
                    "feature_inputs": inputs, "feature_inputs_sha256": _digest(inputs), "sources": source_files}}
                record_forecast(latest, shadow_config, forecast_metadata, as_of)
            prospective = evaluate_prospective(dataset, shadow_config)
            protocol = registration["protocol"]
            current = prospective["current_model"]
            enough = (current["dates"] >= protocol["minimum_complete_dates"]
                      and current["ranked_signal_count"] >= protocol["minimum_ranked_signals"]
                      and current["ranked_signal_windows"] >= protocol["minimum_nonoverlap_signal_windows"]
                      and not prospective["outcome_review_days"])
            report = {"status": "OBSERVING" if ready else "STALE_DATA", "as_of": str(as_of.date()),
                      "updated_at": pd.Timestamp.now("UTC").isoformat(), "registration_sha256": checksum,
                      "model_sha256": registration["files"]["model.joblib"], "timely": bool(timely),
                      "decision_context": context, "prospective": prospective,
                      "minimum_observation_complete": bool(enough), "policy_changed": False, "trading_enabled": False}
            if prospective["outcome_review_days"]:
                report["status"] = "DATA_REVIEW_REQUIRED"
            write_frame(root / "latest_predictions.csv", latest)
            write_json(root / "status.json", report)
            print(f"[SHADOW] {report['status']}: frozen model; eligible dates={prospective['eligible_dates']}", flush=True)
            return report
    except Exception as exc:
        # A shadow failure remains visible without substituting another model or blocking daily forecasts.
        report = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
                  "updated_at": pd.Timestamp.now("UTC").isoformat(), "trading_enabled": False}
        try:
            with prediction_lock(root):
                write_json(root / "status.json", report)
        except OSError:
            pass
        print(f"[SHADOW] ERROR: {report['error']}", flush=True)
        return report
