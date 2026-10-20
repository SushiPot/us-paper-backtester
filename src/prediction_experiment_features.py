"""Causal OHLCV factors inspired by Qlib's public Alpha158 definitions (not all 158)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .prediction_features import FEATURES, build_dataset


WINDOWS = (5, 10, 20, 30, 60)
EXTRA_FEATURES = ["bar_body", "bar_range", "body_range", "upper_open", "upper_range",
                  "lower_open", "lower_range", "close_shift_open", "close_shift_range",
                  "open_close", "high_close", "low_close"] + [
    f"{name}_{window}" for window in WINDOWS
    for name in ("roc", "mean_close", "std_close", "max_high", "min_low", "mean_volume", "std_volume")]
ENRICHED_FEATURES = [*FEATURES, *EXTRA_FEATURES]


def build_experiment_dataset(frames, config):
    core = build_dataset(frames, config)
    calendar = frames["SPY"].index
    rows = []
    for symbol in config.symbols:
        if symbol not in frames:
            continue
        data = frames[symbol].reindex(calendar)
        opening, high, low, close, volume = (data[key] for key in ("open", "high", "low", "close", "volume"))
        span = high - low + 1e-12
        upper = high - np.maximum(opening, close)
        lower = np.minimum(opening, close) - low
        shift = 2 * close - high - low
        factors = pd.DataFrame({
            "bar_body": (close - opening) / opening, "bar_range": (high - low) / opening,
            "body_range": (close - opening) / span, "upper_open": upper / opening,
            "upper_range": upper / span, "lower_open": lower / opening, "lower_range": lower / span,
            "close_shift_open": shift / opening, "close_shift_range": shift / span,
            "open_close": opening / close, "high_close": high / close, "low_close": low / close,
        }, index=calendar)
        for window in WINDOWS:
            factors[f"roc_{window}"] = close.shift(window) / close
            factors[f"mean_close_{window}"] = close.rolling(window).mean() / close
            factors[f"std_close_{window}"] = close.rolling(window).std() / close
            factors[f"max_high_{window}"] = high.rolling(window).max() / close
            factors[f"min_low_{window}"] = low.rolling(window).min() / close
            factors[f"mean_volume_{window}"] = volume.rolling(window).mean() / (volume + 1e-12)
            factors[f"std_volume_{window}"] = volume.rolling(window).std() / (volume + 1e-12)
        rows.append(factors.assign(date=calendar, symbol=symbol))
    enriched = core.merge(pd.concat(rows, ignore_index=True), on=["date", "symbol"], validate="one_to_one")
    enriched = enriched.replace([np.inf, -np.inf], np.nan).dropna(subset=ENRICHED_FEATURES)
    # Both feature families must see identical rows, not different surviving winners.
    return enriched.sort_values(["date", "symbol"]).reset_index(drop=True), {
        "core_rows": len(core), "common_rows": len(enriched), "feature_rows_excluded": len(core) - len(enriched),
        "core_features": len(FEATURES), "enriched_features": len(ENRICHED_FEATURES),
    }
