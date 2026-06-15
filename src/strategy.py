from __future__ import annotations

import pandas as pd


def should_buy(row: pd.Series, rsi_limit: float = 70.0) -> bool:
    """买入条件：金叉、RSI 小于阈值、放量。"""
    rsi_value = row["rsi"] if "rsi" in row else row["rsi14"]
    return bool(
        row["golden_cross"]
        and rsi_value < rsi_limit
        and row["volume"] > row["volume_ma20"]
    )


def should_sell_by_signal(row: pd.Series) -> bool:
    """卖出技术信号：死叉。"""
    return bool(row["death_cross"])
