"""Read-only checks for the daily workflow; no downloads or historical backtests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

from .market_calendar import completed_session
from .prediction_data import PredictionConfig, file_hash


def runtime_checks(output_dir: Path = Path("outputs"), *, include_shadow: bool = True) -> list[dict]:
    rows = []
    for name in ("numpy", "pandas", "sklearn", "requests", "flask", "pandas_market_calendars"):
        available = importlib.util.find_spec(name) is not None
        rows.append({"check": name, "status": "OK" if available else "ERROR", "detail": "installed" if available else "missing core dependency"})
    directory = Path(output_dir) / "prediction"
    try:
        manifest = json.loads((directory / "model_manifest.json").read_text(encoding="utf-8"))
        valid = manifest["model_sha256"] == file_hash(directory / "model.joblib")
        rows.append({"check": "model", "status": "OK" if valid else "WARN", "detail": "checksum verified" if valid else "daily run will retrain"})
    except (OSError, ValueError, KeyError, TypeError):
        rows.append({"check": "model", "status": "WARN", "detail": "model unavailable; daily run will train"})
    try:
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("Invalid daily report")
        try:
            state = json.loads((directory / "status.json").read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError):
            state = {}
        expected = str(completed_session().date())
        # A completed report can survive a later failed or interrupted run.
        current = (report.get("as_of") == expected and report.get("data_ready") is True
                   and state.get("data_ready") is True
                   and state.get("status") in {"RESEARCH_ONLY", "RESEARCH_PASS"}
                   and all(state.get(key) == report.get(key) and report.get(key) is not None
                           for key in ("status", "as_of", "updated_at", "model_sha256", "current_data_fingerprint")))
        rows.append({"check": "daily bars", "status": "OK" if current else "WARN",
                     "detail": f"report_session={report.get('as_of', 'unknown')}; expected={expected}; "
                               f"report_data_ready={report.get('data_ready')}; run_status={state.get('status', 'UNKNOWN')}"})
        unsafe = report.get("trading_enabled") is not False or (bool(state) and state.get("trading_enabled") is not False)
        rows.append({"check": "real trading", "status": "ERROR" if unsafe else "OK", "detail": "must remain disabled"})
    except (OSError, ValueError, KeyError, TypeError):
        rows.append({"check": "daily bars", "status": "WARN", "detail": "run daily update first"})
    try:
        account_path = Path(output_dir) / "virtual_account.csv"
        if account_path.exists():
            account = pd.read_csv(account_path, nrows=10)
            cash = pd.to_numeric(account["virtual_cash"], errors="raise")
            valid = cash.notna().all() and (cash >= -0.01).all()
            rows.append({"check": "paper cash", "status": "OK" if valid else "ERROR", "detail": "nonnegative cash invariant"})
    except (OSError, ValueError, KeyError, pd.errors.ParserError):
        rows.append({"check": "paper cash", "status": "ERROR", "detail": "cannot validate existing account"})
    if include_shadow:
        from .prediction_shadow_health import shadow_health

        shadow = shadow_health(PredictionConfig(output_dir=directory))
        rows.append({key: shadow[key] for key in ("check", "status", "detail")})
    return rows


def print_checks(output_dir: Path = Path("outputs"), *, include_shadow: bool = True) -> int:
    rows = runtime_checks(output_dir, include_shadow=include_shadow)
    for row in rows:
        print(f"[{row['status']}] {row['check']}: {row['detail']}", flush=True)
    return int(any(row["status"] == "ERROR" for row in rows))
