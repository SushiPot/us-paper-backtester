from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from .agents.base import read_csv
from .config import LocalPaperConfig


ADAPTIVE_PROFILE_FILE = "adaptive_strategy_profile.json"


def write_adaptive_profile(output_dir: Path = Path("outputs")) -> dict[str, object]:
    """?????????????????????????????"""
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = read_csv(output_dir / "strategy_variant_scores.csv")
    health = read_csv(output_dir / "strategy_health.csv")
    walk_forward = read_csv(output_dir / "walk_forward_summary.csv")

    profile = _build_profile(variants, health, walk_forward)
    path = output_dir / ADAPTIVE_PROFILE_FILE
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([profile]).to_csv(output_dir / "adaptive_strategy_profile.csv", index=False, encoding="utf-8-sig")
    return profile


def apply_adaptive_profile(
    config: LocalPaperConfig,
    output_dir: Path | None = None,
    force: bool = False,
) -> tuple[LocalPaperConfig, dict[str, object]]:
    """?????????????? force=True ???????????"""
    base_dir = output_dir or config.output_dir
    path = base_dir / ADAPTIVE_PROFILE_FILE
    if not path.exists():
        return config, {"applied": False, "reason": "adaptive profile not found"}

    profile = json.loads(path.read_text(encoding="utf-8"))
    gate = str(profile.get("gate_status", ""))
    if not force and gate != "ALLOW_ADAPTIVE":
        profile["applied"] = False
        profile["reason"] = f"adaptive gate is {gate}"
        return config, profile

    enabled = str(profile.get("enabled_buy_strategies", ""))
    strategies = [part.strip() for part in enabled.split(",") if part.strip()]
    if not strategies:
        profile["applied"] = False
        profile["reason"] = "profile has no enabled strategies"
        return config, profile

    updated = replace(
        config,
        enabled_buy_strategies=strategies,
        trend_position_scale=float(profile.get("trend_position_scale", config.trend_position_scale)),
        trend_volume_ratio=float(profile.get("trend_volume_ratio", config.trend_volume_ratio)),
        trend_max_distance_fast_ma=float(
            profile.get("trend_max_distance_fast_ma", config.trend_max_distance_fast_ma)
        ),
    )
    profile["applied"] = True
    profile["reason"] = "adaptive profile applied"
    return updated, profile


def _build_profile(variants: pd.DataFrame, health: pd.DataFrame, walk_forward: pd.DataFrame) -> dict[str, object]:
    if variants.empty:
        return {
            "profile_name": "none",
            "gate_status": "NO_VARIANTS",
            "reason": "No strategy variant scores available.",
        }

    best = variants.iloc[0]
    health_row = health.iloc[-1] if not health.empty else {}
    walk_row = walk_forward.iloc[-1] if not walk_forward.empty else {}
    health_action = str(_get(health_row, "recommended_action", ""))
    health_status = str(_get(health_row, "health_status", ""))
    stability_score = float(_get(walk_row, "stability_score", 0.0))
    variant_score = float(_get(best, "variant_score", 0.0))

    gate_status = "ALLOW_ADAPTIVE"
    reasons = []
    if health_action == "OBSERVE_ONLY" or health_status == "OBSERVATION":
        gate_status = "OBSERVE_ONLY"
        reasons.append("strategy health gate is observation-only")
    if stability_score < 60:
        gate_status = "WALK_FORWARD_WEAK"
        reasons.append("walk-forward stability is below 60")
    if variant_score < 60:
        gate_status = "VARIANT_WEAK"
        reasons.append("best variant score is below 60")

    return {
        "profile_name": str(best.get("variant", "")),
        "enabled_buy_strategies": str(best.get("enabled_buy_strategies", "")),
        "trend_position_scale": float(best.get("trend_position_scale", 0.0)),
        "trend_volume_ratio": float(best.get("trend_volume_ratio", 0.0)),
        "trend_max_distance_fast_ma": float(best.get("trend_max_distance_fast_ma", 0.0)),
        "variant_score": variant_score,
        "walk_forward_score": stability_score,
        "health_score": float(_get(health_row, "overall_score", 0.0)),
        "health_status": health_status,
        "health_action": health_action,
        "gate_status": gate_status,
        "reason": "?".join(reasons) if reasons else "all adaptive gates passed",
    }


def _get(row, key: str, default):
    try:
        value = row[key]
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default
