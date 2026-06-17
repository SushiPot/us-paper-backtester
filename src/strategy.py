from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd


STRICT_GOLDEN_CROSS = "strict_golden_cross"
TREND_FOLLOW = "trend_follow"


@dataclass(frozen=True)
class BuySignalEvaluation:
    """买入信号评估结果，包含触发策略和未触发原因。"""

    should_buy: bool
    strategy_name: str
    score: float
    reason: str


def should_buy(row: pd.Series, rsi_limit: float = 70.0) -> bool:
    """买入条件：金叉、RSI 小于阈值、放量。"""
    return evaluate_buy_signal(row, rsi_limit=rsi_limit, enabled_strategies=[STRICT_GOLDEN_CROSS]).should_buy


def evaluate_buy_signal(
    row: pd.Series,
    rsi_limit: float = 70.0,
    enabled_strategies: list[str] | tuple[str, ...] | None = None,
    trend_min_rsi: float = 45.0,
    trend_volume_ratio: float = 0.80,
    trend_max_distance_fast_ma: float = 0.08,
    trend_min_return_5d: float = -0.03,
) -> BuySignalEvaluation:
    """同时评估严格金叉和趋势确认策略。"""
    strategies = list(enabled_strategies or [STRICT_GOLDEN_CROSS])
    evaluations = []
    if STRICT_GOLDEN_CROSS in strategies:
        evaluations.append(_evaluate_strict_golden_cross(row, rsi_limit))
    if TREND_FOLLOW in strategies:
        evaluations.append(
            _evaluate_trend_follow(
                row,
                rsi_limit,
                trend_min_rsi,
                trend_volume_ratio,
                trend_max_distance_fast_ma,
                trend_min_return_5d,
            )
        )

    for evaluation in evaluations:
        if evaluation.should_buy:
            return evaluation

    if not evaluations:
        return BuySignalEvaluation(False, "disabled", 0.0, "未启用任何买入策略")

    best = max(evaluations, key=lambda item: item.score)
    reasons = "；".join(f"{item.strategy_name}: {item.reason}" for item in evaluations if item.reason)
    return BuySignalEvaluation(False, best.strategy_name, best.score, reasons)


def should_sell_by_signal(row: pd.Series) -> bool:
    """卖出技术信号：死叉。"""
    return bool(row["death_cross"])


def _evaluate_strict_golden_cross(row: pd.Series, rsi_limit: float) -> BuySignalEvaluation:
    rsi_value = _number(row, "rsi", _number(row, "rsi14", math.nan))
    checks = {
        "MA20当日金叉MA60": bool(row.get("golden_cross", False)),
        f"RSI<{rsi_limit:g}": bool(math.isfinite(rsi_value) and rsi_value < rsi_limit),
        "成交量>20日均量": bool(_number(row, "volume", 0.0) > _number(row, "volume_ma20", math.inf)),
    }
    passed = sum(checks.values())
    if all(checks.values()):
        return BuySignalEvaluation(True, STRICT_GOLDEN_CROSS, 100.0, "MA20上穿MA60且RSI<70且放量")
    return BuySignalEvaluation(False, STRICT_GOLDEN_CROSS, passed / len(checks) * 100.0, _failed_reason(checks))


def _evaluate_trend_follow(
    row: pd.Series,
    rsi_limit: float,
    trend_min_rsi: float,
    trend_volume_ratio: float,
    trend_max_distance_fast_ma: float,
    trend_min_return_5d: float,
) -> BuySignalEvaluation:
    rsi_value = _number(row, "rsi", _number(row, "rsi14", math.nan))
    volume = _number(row, "volume", 0.0)
    volume_ma20 = _number(row, "volume_ma20", math.inf)
    distance_fast_ma = _number(row, "distance_fast_ma", math.inf)
    return_5d = _number(row, "return_5d", math.nan)
    checks = {
        "MA20>MA60趋势向上": bool(row.get("trend_up", False)),
        "收盘价在MA20上方": bool(row.get("above_fast_ma", False)),
        f"{trend_min_rsi:g}<=RSI<{rsi_limit:g}": bool(math.isfinite(rsi_value) and trend_min_rsi <= rsi_value < rsi_limit),
        f"成交量>=20日均量的{trend_volume_ratio:.0%}": bool(volume_ma20 > 0 and volume >= volume_ma20 * trend_volume_ratio),
        f"价格距离MA20不超过{trend_max_distance_fast_ma:.0%}": bool(
            math.isfinite(distance_fast_ma) and distance_fast_ma <= trend_max_distance_fast_ma
        ),
        f"5日跌幅不超过{abs(trend_min_return_5d):.0%}": bool(math.isfinite(return_5d) and return_5d >= trend_min_return_5d),
    }
    passed = sum(checks.values())
    if all(checks.values()):
        return BuySignalEvaluation(True, TREND_FOLLOW, 100.0, "MA20>MA60趋势确认且RSI/成交量/乖离率通过")
    return BuySignalEvaluation(False, TREND_FOLLOW, passed / len(checks) * 100.0, _failed_reason(checks))


def _failed_reason(checks: dict[str, bool]) -> str:
    failed = [name for name, passed in checks.items() if not passed]
    return "未满足: " + "、".join(failed) if failed else ""


def _number(row: pd.Series, key: str, default: float) -> float:
    value = row[key] if key in row else default
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default
