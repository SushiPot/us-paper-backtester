from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import LocalPaperConfig
from .database import get_store
from .strategy import STRICT_GOLDEN_CROSS, TREND_FOLLOW, evaluate_buy_signal


RELATIVE_STRENGTH_FILTERED = "enabled_blend_relative_strength_filter"


class SignalEvaluationAnalyzer:
    """?????????????? precision / recall / F1?"""

    def __init__(
        self,
        config: LocalPaperConfig | None = None,
        output_dir: Path = Path("outputs"),
    ) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, market_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        rows = []
        relative_strength_lookup = self._build_historical_relative_strength(market_data)
        for strategy_name in ["enabled_blend", RELATIVE_STRENGTH_FILTERED, TREND_FOLLOW, STRICT_GOLDEN_CROSS]:
            for horizon in self.config.signal_eval_horizons:
                rows.extend(self._evaluate_strategy(market_data, strategy_name, horizon, relative_strength_lookup))

        detail = pd.DataFrame(rows)
        summary = self._summary(detail)
        detail.to_csv(self.output_dir / "signal_evaluation.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "signal_evaluation_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(summary)
        get_store().append_generic_frame("signal_evaluation", "signal_evaluation.csv", detail)
        get_store().append_generic_frame("signal_evaluation_summary", "signal_evaluation_summary.csv", summary)
        return summary

    def _evaluate_strategy(
        self,
        market_data: dict[str, pd.DataFrame],
        strategy_name: str,
        horizon: int,
        relative_strength_lookup: dict[tuple[str, str], dict[str, object]],
    ) -> list[dict[str, object]]:
        rows = []
        threshold = self.config.signal_eval_positive_return_threshold
        for symbol, frame in market_data.items():
            clean = frame.dropna().sort_index()
            if len(clean) <= horizon + 120:
                continue
            future_return = clean["close"].astype(float).shift(-horizon) / clean["close"].astype(float) - 1
            for index, row in clean.iloc[:-horizon].iterrows():
                evaluation = self._evaluate_row(row, strategy_name)
                date_text = pd.Timestamp(index).date().isoformat()
                rs_row = relative_strength_lookup.get((date_text, symbol), {})
                filter_passed, filter_reason = self._relative_strength_filter_ok(rs_row)
                predicted_positive = bool(evaluation.should_buy)
                if strategy_name == RELATIVE_STRENGTH_FILTERED:
                    predicted_positive = predicted_positive and filter_passed
                actual_positive = bool(future_return.loc[index] >= threshold)
                rows.append(
                    {
                        "time": pd.Timestamp.now(),
                        "symbol": symbol,
                        "date": date_text,
                        "strategy_name": strategy_name,
                        "triggered_strategy": evaluation.strategy_name,
                        "horizon_days": horizon,
                        "threshold_return": threshold,
                        "predicted_positive": predicted_positive,
                        "actual_positive": actual_positive,
                        "future_return": float(future_return.loc[index]),
                        "signal_score": float(evaluation.score),
                        "close": float(row["close"]),
                        "relative_strength_rank": rs_row.get("rank", pd.NA),
                        "relative_strength_score": rs_row.get("relative_strength_score", pd.NA),
                        "relative_strength_status": rs_row.get("status", "NO_DATA"),
                        "relative_strength_filter_passed": filter_passed,
                        "relative_strength_filter_reason": filter_reason,
                    }
                )
        return rows

    def _evaluate_row(self, row: pd.Series, strategy_name: str):
        if strategy_name in {"enabled_blend", RELATIVE_STRENGTH_FILTERED}:
            enabled = self.config.enabled_buy_strategies
        else:
            enabled = [strategy_name]
        return evaluate_buy_signal(
            row,
            rsi_limit=self.config.rsi_limit,
            enabled_strategies=enabled,
            trend_min_rsi=self.config.trend_min_rsi,
            trend_volume_ratio=self.config.trend_volume_ratio,
            trend_max_distance_fast_ma=self.config.trend_max_distance_fast_ma,
            trend_min_return_5d=self.config.trend_min_return_5d,
        )

    def _build_historical_relative_strength(
        self,
        market_data: dict[str, pd.DataFrame],
    ) -> dict[tuple[str, str], dict[str, object]]:
        """??????????????????????????"""
        raw_frames = []
        spy = market_data.get("SPY")
        spy_close = pd.Series(dtype=float)
        if spy is not None and not spy.empty:
            spy_close = spy.dropna().sort_index()["close"].astype(float)

        for symbol, frame in market_data.items():
            if symbol == "SPCX":
                continue
            clean = frame.dropna().sort_index()
            if len(clean) < 130:
                continue

            close = clean["close"].astype(float)
            spy_20d = spy_close.pct_change(20).reindex(clean.index).ffill().fillna(0.0)
            spy_60d = spy_close.pct_change(60).reindex(clean.index).ffill().fillna(0.0)
            raw = pd.DataFrame(
                {
                    "date": clean.index,
                    "symbol": symbol,
                    "return_20d": close.pct_change(20),
                    "return_60d": close.pct_change(60),
                    "return_120d": close.pct_change(120),
                    "relative_spy_20d": close.pct_change(20) - spy_20d,
                    "relative_spy_60d": close.pct_change(60) - spy_60d,
                    "volatility_20d": close.pct_change().rolling(20).std() * (252**0.5),
                    "distance_fast_ma": clean.get("distance_fast_ma", pd.Series(0.0, index=clean.index)),
                    "rsi": clean.get("rsi", clean.get("rsi14", pd.Series(0.0, index=clean.index))),
                    "trend_up": clean.get("trend_up", pd.Series(False, index=clean.index)).astype(bool),
                    "above_fast_ma": clean.get("above_fast_ma", pd.Series(False, index=clean.index)).astype(bool),
                }
            )
            raw_frames.append(raw.dropna())

        if not raw_frames:
            return {}

        raw_all = pd.concat(raw_frames, ignore_index=True)
        scored_frames = [
            self._score_relative_strength_group(date, group.drop(columns=["date"]))
            for date, group in raw_all.groupby("date", sort=True)
        ]
        scored = pd.concat(scored_frames, ignore_index=True)
        lookup: dict[tuple[str, str], dict[str, object]] = {}
        for row in scored.to_dict(orient="records"):
            date_text = pd.Timestamp(row["date"]).date().isoformat()
            symbol = str(row["symbol"])
            lookup[(date_text, symbol)] = {
                "rank": int(row["rank"]),
                "relative_strength_score": float(row["relative_strength_score"]),
                "status": str(row["status"]),
            }
        return lookup

    def _score_relative_strength_group(self, date: pd.Timestamp, group: pd.DataFrame) -> pd.DataFrame:
        scored = group.copy()
        scored["momentum_rank"] = (
            _pct_rank(scored["return_20d"]) * 0.40
            + _pct_rank(scored["return_60d"]) * 0.35
            + _pct_rank(scored["return_120d"]) * 0.25
        )
        scored["relative_rank"] = _pct_rank(scored["relative_spy_20d"]) * 0.55 + _pct_rank(scored["relative_spy_60d"]) * 0.45
        scored["volatility_rank"] = 1.0 - _pct_rank(scored["volatility_20d"])
        scored["trend_score"] = scored["trend_up"].astype(float) * 0.55 + scored["above_fast_ma"].astype(float) * 0.45
        scored["pullback_score"] = scored["distance_fast_ma"].astype(float).apply(_pullback_score)
        scored["rsi_score"] = scored["rsi"].astype(float).apply(_rsi_score)
        scored["relative_strength_score"] = (
            scored["momentum_rank"] * 38
            + scored["relative_rank"] * 27
            + scored["trend_score"] * 18
            + scored["pullback_score"] * 10
            + scored["rsi_score"] * 5
            + scored["volatility_rank"] * 2
        ).round(2)
        scored = scored.sort_values("relative_strength_score", ascending=False).reset_index(drop=True)
        scored["rank"] = scored.index + 1
        scored["status"] = scored.apply(
            lambda row: "PASS"
            if row["rank"] <= self.config.relative_strength_top_n
            and row["relative_strength_score"] >= self.config.relative_strength_min_score
            else "WATCH",
            axis=1,
        )
        scored["date"] = date
        return scored

    def _relative_strength_filter_ok(self, row: dict[str, object]) -> tuple[bool, str]:
        if not row:
            return False, "NO_DATA"
        rank = int(float(row.get("rank", 999)))
        score = float(row.get("relative_strength_score", 0.0))
        status = str(row.get("status", "WATCH"))
        reasons = []
        if rank > self.config.relative_strength_top_n:
            reasons.append(f"rank>{self.config.relative_strength_top_n}")
        if score < self.config.relative_strength_min_score:
            reasons.append(f"score<{self.config.relative_strength_min_score:.0f}")
        if status != "PASS":
            reasons.append(f"status={status}")
        if reasons:
            return False, "; ".join(reasons)
        return True, "PASS"

    @staticmethod
    def _summary(detail: pd.DataFrame) -> pd.DataFrame:
        if detail.empty:
            return pd.DataFrame(
                [
                    {
                        "time": pd.Timestamp.now(),
                        "strategy_name": "none",
                        "horizon_days": 0,
                        "sample_count": 0,
                        "signal_count": 0,
                        "opportunity_count": 0,
                        "true_positive": 0,
                        "false_positive": 0,
                        "false_negative": 0,
                        "precision": 0.0,
                        "recall": 0.0,
                        "f1": 0.0,
                        "avg_signal_future_return": 0.0,
                        "avg_all_future_return": 0.0,
                        "edge_vs_all_future_return": 0.0,
                    }
                ]
            )

        rows = []
        for (strategy_name, horizon), group in detail.groupby(["strategy_name", "horizon_days"], dropna=False):
            predicted = group["predicted_positive"].astype(bool)
            actual = group["actual_positive"].astype(bool)
            tp = int((predicted & actual).sum())
            fp = int((predicted & ~actual).sum())
            fn = int((~predicted & actual).sum())
            signal_count = int(predicted.sum())
            opportunity_count = int(actual.sum())
            precision = tp / signal_count if signal_count else 0.0
            recall = tp / opportunity_count if opportunity_count else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            signal_returns = group.loc[predicted, "future_return"].astype(float)
            avg_signal_future_return = float(signal_returns.mean()) if len(signal_returns) else 0.0
            avg_all_future_return = float(group["future_return"].astype(float).mean())
            rows.append(
                {
                    "time": pd.Timestamp.now(),
                    "strategy_name": strategy_name,
                    "horizon_days": int(horizon),
                    "sample_count": int(len(group)),
                    "signal_count": signal_count,
                    "opportunity_count": opportunity_count,
                    "true_positive": tp,
                    "false_positive": fp,
                    "false_negative": fn,
                    "precision": precision,
                    "recall": recall,
                    "f1": f1,
                    "avg_signal_future_return": avg_signal_future_return,
                    "avg_all_future_return": avg_all_future_return,
                    "edge_vs_all_future_return": avg_signal_future_return - avg_all_future_return,
                }
            )
        return pd.DataFrame(rows).sort_values(
            ["edge_vs_all_future_return", "precision", "f1", "horizon_days"],
            ascending=[False, False, False, True],
        )

    def _write_report(self, summary: pd.DataFrame) -> None:
        lines = [
            "# Signal Evaluation Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "Label definition: future return over the horizon is greater than or equal to "
            f"{self.config.signal_eval_positive_return_threshold:.2%}.",
            "",
            "| strategy | horizon | precision | recall | f1 | signals | opportunities | avg_signal_future_return | edge_vs_all |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in summary.to_dict(orient="records"):
            lines.append(
                f"| {row.get('strategy_name', '')} | {row.get('horizon_days', '')} | "
                f"{float(row.get('precision', 0.0)):.2%} | {float(row.get('recall', 0.0)):.2%} | "
                f"{float(row.get('f1', 0.0)):.2%} | {row.get('signal_count', 0)} | "
                f"{row.get('opportunity_count', 0)} | {float(row.get('avg_signal_future_return', 0.0)):.2%} | "
                f"{float(row.get('edge_vs_all_future_return', 0.0)):.2%} |"
            )
        (self.output_dir / "signal_evaluation_report.md").write_text("\n".join(lines), encoding="utf-8")


def _pct_rank(series: pd.Series) -> pd.Series:
    return series.astype(float).rank(pct=True).fillna(0.0)


def _pullback_score(distance_fast_ma: float) -> float:
    if distance_fast_ma < -0.06:
        return 0.1
    if -0.02 <= distance_fast_ma <= 0.04:
        return 1.0
    if 0.04 < distance_fast_ma <= 0.08:
        return 0.6
    if 0.08 < distance_fast_ma <= 0.12:
        return 0.25
    return 0.4


def _rsi_score(rsi: float) -> float:
    if 45 <= rsi <= 62:
        return 1.0
    if 62 < rsi < 70:
        return 0.65
    if 38 <= rsi < 45:
        return 0.5
    return 0.2
