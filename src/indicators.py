from __future__ import annotations

import pandas as pd


def add_indicators(
    data: pd.DataFrame,
    fast_ma: int = 20,
    slow_ma: int = 60,
    rsi_period: int = 14,
) -> pd.DataFrame:
    """添加策略需要的均线、RSI、成交量均线和交叉信号。"""
    result = data.copy()
    result["fast_ma"] = result["close"].rolling(window=fast_ma).mean()
    result["slow_ma"] = result["close"].rolling(window=slow_ma).mean()
    result["ma20"] = result["close"].rolling(window=20).mean()
    result["ma60"] = result["close"].rolling(window=60).mean()
    result["volume_ma20"] = result["volume"].rolling(window=20).mean()
    result["rsi"] = calculate_rsi(result["close"], period=rsi_period)
    result["rsi14"] = calculate_rsi(result["close"], period=14)
    result["return_5d"] = result["close"].pct_change(5)

    prev_fast = result["fast_ma"].shift(1)
    prev_slow = result["slow_ma"].shift(1)
    result["golden_cross"] = (prev_fast <= prev_slow) & (result["fast_ma"] > result["slow_ma"])
    result["death_cross"] = (prev_fast >= prev_slow) & (result["fast_ma"] < result["slow_ma"])
    result["trend_up"] = result["fast_ma"] > result["slow_ma"]
    result["above_fast_ma"] = result["close"] > result["fast_ma"]
    result["distance_fast_ma"] = result["close"] / result["fast_ma"] - 1
    return result


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """使用 Wilder 平滑算法计算 RSI。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))
