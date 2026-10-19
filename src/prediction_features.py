"""Features known at session close and labels from subsequent executable opens."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .prediction_data import PredictionConfig


FEATURES = ["return_1", "return_5", "return_20", "return_60", "volatility_20",
            "ma_5_20", "ma_20_60", "range_10", "volume_ratio_20", "relative_spy_20",
            "spy_return_5", "spy_volatility_20"]


def build_dataset(frames: dict[str, pd.DataFrame], config: PredictionConfig) -> pd.DataFrame:
    if "SPY" not in frames:
        raise ValueError("Verified SPY history is required")
    spy = frames["SPY"]
    calendar = spy.index
    dates = pd.Series(calendar, index=calendar)
    spy_daily = spy.close.pct_change(fill_method=None)
    spy_return = spy.open.shift(-(config.horizon + 1)) / spy.open.shift(-1) - 1
    rows = []
    for symbol in config.symbols:
        if symbol not in frames:
            continue
        data = frames[symbol].reindex(calendar)
        close = data.close
        daily = close.pct_change(fill_method=None)
        features = pd.DataFrame(index=calendar)
        for lag in (1, 5, 20, 60):
            features[f"return_{lag}"] = close.pct_change(lag, fill_method=None)
        features["volatility_20"] = daily.rolling(20).std()
        features["ma_5_20"] = close.rolling(5).mean() / close.rolling(20).mean() - 1
        features["ma_20_60"] = close.rolling(20).mean() / close.rolling(60).mean() - 1
        features["range_10"] = ((data.high - data.low) / close).rolling(10).mean()
        features["volume_ratio_20"] = data.volume / data.volume.rolling(20).mean()
        features["relative_spy_20"] = features.return_20 - spy.close.pct_change(20, fill_method=None)
        features["spy_return_5"] = spy.close.pct_change(5, fill_method=None)
        features["spy_volatility_20"] = spy_daily.rolling(20).std()
        features["symbol"] = symbol
        features["date"] = calendar
        features["entry_date"] = dates.shift(-1)
        features["label_end"] = dates.shift(-(config.horizon + 1))
        features["gross_return"] = data.open.shift(-(config.horizon + 1)) / data.open.shift(-1) - 1
        features["spy_return"] = spy_return
        features["target"] = np.where(features.gross_return.notna(),
                                      (features.gross_return > config.cost_bps / 10000).astype(float), np.nan)
        features = features.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES)
        rows.append(features)
    if not rows:
        raise ValueError("No usable prediction features")
    dataset = pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)
    labels = dataset.groupby("date").target
    dataset["complete_outcomes"] = labels.transform("count") == labels.transform("size")
    return dataset


def time_partitions(dataset: pd.DataFrame, config: PredictionConfig) -> dict[str, pd.DataFrame]:
    result = {}
    lower = pd.Timestamp.min
    labeled = dataset.dropna(subset=["target", "gross_return", "spy_return", "label_end"])
    for name, end in (("train", config.train_end), ("validation", config.validation_end), ("test", config.test_end)):
        end = pd.Timestamp(end)
        part = labeled.loc[(labeled.date > lower) & (labeled.date <= end) & (labeled.label_end <= end)].copy()
        minimum = config.min_train_dates if name == "train" else config.min_eval_dates
        if part.date.nunique() < minimum or part.symbol.nunique() < config.min_symbols or part.target.nunique() < 2:
            raise ValueError(f"Insufficient independent dates/symbols/classes in {name}: dates={part.date.nunique()}, symbols={part.symbol.nunique()}")
        result[name] = part
        lower = end
    result["forward"] = labeled.loc[labeled.date > lower].copy()
    return result
