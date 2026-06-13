from __future__ import annotations

import pandas as pd


def should_buy(row: pd.Series) -> bool:
    """买入条件：金叉、RSI 小于 70、放量。"""
    return bool(
        row["golden_cross"]
        and row["rsi14"] < 70
        and row["volume"] > row["volume_ma20"]
    )


def should_sell_by_signal(row: pd.Series) -> bool:
    """卖出技术信号：死叉。"""
    return bool(row["death_cross"])
