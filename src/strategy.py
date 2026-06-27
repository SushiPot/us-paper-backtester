from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd


STRICT_GOLDEN_CROSS = "strict_golden_cross"
TREND_FOLLOW = "trend_follow"


@dataclass(frozen=True)
class BuySignalEvaluation:
    """??????????????????????"""

    should_buy: bool
    strategy_name: str
    score: float
    reason: str


def should_buy(row: pd.Series, rsi_limit: float = 70.0) -> bool:
    """????????RSI ????????"""
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
    """????????????????"""
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
        return BuySignalEvaluation(False, "disabled", 0.0, "?????????")

    best = max(evaluations, key=lambda item: item.score)
    reasons = "?".join(f"{item.strategy_name}: {item.reason}" for item in evaluations if item.reason)
    return BuySignalEvaluation(False, best.strategy_name, best.score, reasons)


def should_sell_by_signal(row: pd.Series) -> bool:
    """??????????"""
    return bool(row["death_cross"])


def signal_metric_snapshot(row: pd.Series) -> dict[str, float | bool]:
    """????????????????????????????"""
    volume = _number(row, "volume", 0.0)
    volume_ma20 = _number(row, "volume_ma20", 0.0)
    fast_ma = _number(row, "fast_ma", _number(row, "ma20", 0.0))
    slow_ma = _number(row, "slow_ma", _number(row, "ma60", 0.0))
    close = _number(row, "close", 0.0)
    return {
        "close": close,
        "fast_ma": fast_ma,
        "slow_ma": slow_ma,
        "ma_gap_pct": fast_ma / slow_ma - 1 if slow_ma else 0.0,
        "rsi": _number(row, "rsi", _number(row, "rsi14", 0.0)),
        "volume": volume,
        "volume_ma20": volume_ma20,
        "volume_ratio": volume / volume_ma20 if volume_ma20 else 0.0,
        "distance_fast_ma": _number(row, "distance_fast_ma", 0.0),
        "return_5d": _number(row, "return_5d", 0.0),
        "golden_cross": bool(row.get("golden_cross", False)),
        "death_cross": bool(row.get("death_cross", False)),
        "trend_up": bool(row.get("trend_up", False)),
    }


def _evaluate_strict_golden_cross(row: pd.Series, rsi_limit: float) -> BuySignalEvaluation:
    rsi_value = _number(row, "rsi", _number(row, "rsi14", math.nan))
    checks = {
        "MA20????MA60": bool(row.get("golden_cross", False)),
        f"RSI<{rsi_limit:g}": bool(math.isfinite(rsi_value) and rsi_value < rsi_limit),
        "???>20???": bool(_number(row, "volume", 0.0) > _number(row, "volume_ma20", math.inf)),
    }
    passed = sum(checks.values())
    if all(checks.values()):
        return BuySignalEvaluation(True, STRICT_GOLDEN_CROSS, 100.0, "MA20??MA60?RSI<70???")
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
        "MA20>MA60????": bool(row.get("trend_up", False)),
        "????MA20??": bool(row.get("above_fast_ma", False)),
        f"{trend_min_rsi:g}<=RSI<{rsi_limit:g}": bool(math.isfinite(rsi_value) and trend_min_rsi <= rsi_value < rsi_limit),
        f"???>=20????{trend_volume_ratio:.0%}": bool(volume_ma20 > 0 and volume >= volume_ma20 * trend_volume_ratio),
        f"????MA20???{trend_max_distance_fast_ma:.0%}": bool(
            math.isfinite(distance_fast_ma) and distance_fast_ma <= trend_max_distance_fast_ma
        ),
        f"5??????{abs(trend_min_return_5d):.0%}": bool(math.isfinite(return_5d) and return_5d >= trend_min_return_5d),
    }
    passed = sum(checks.values())
    if all(checks.values()):
        return BuySignalEvaluation(True, TREND_FOLLOW, 100.0, "MA20>MA60?????RSI/???/?????")
    return BuySignalEvaluation(False, TREND_FOLLOW, passed / len(checks) * 100.0, _failed_reason(checks))


def _failed_reason(checks: dict[str, bool]) -> str:
    failed = [name for name, passed in checks.items() if not passed]
    return "???: " + "?".join(failed) if failed else ""


def _number(row: pd.Series, key: str, default: float) -> float:
    value = row[key] if key in row else default
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default
