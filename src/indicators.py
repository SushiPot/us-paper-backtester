from __future__ import annotations

import pandas as pd


def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
    """添加策略需要的均线、RSI、成交量均线和交叉信号。"""
    result = data.copy()
    result["ma20"] = result["close"].rolling(window=20).mean()
    result["ma60"] = result["close"].rolling(window=60).mean()
    result["volume_ma20"] = result["volume"].rolling(window=20).mean()
    result["rsi14"] = calculate_rsi(result["close"], period=14)

    prev_ma20 = result["ma20"].shift(1)
    prev_ma60 = result["ma60"].shift(1)
    result["golden_cross"] = (prev_ma20 <= prev_ma60) & (result["ma20"] > result["ma60"])
    result["death_cross"] = (prev_ma20 >= prev_ma60) & (result["ma20"] < result["ma60"])
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
