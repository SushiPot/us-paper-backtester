from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import LocalPaperConfig
from .database import get_store
from .universe import load_tradable_universe


class RelativeStrengthRanker:
    """按相对强弱给股票池排序，帮助模拟盘少买弱势标的。"""

    def __init__(self, config: LocalPaperConfig | None = None, output_dir: Path = Path("outputs")) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, market_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        allowed = load_tradable_universe(self.output_dir)
        if allowed:
            market_data = {symbol: frame for symbol, frame in market_data.items() if symbol in allowed}
        rows = [self._raw_row(symbol, frame, market_data) for symbol, frame in market_data.items()]
        frame = pd.DataFrame([row for row in rows if row])
        if frame.empty:
            frame = pd.DataFrame(
                columns=[
                    "time",
                    "symbol",
                    "rank",
                    "relative_strength_score",
                    "status",
                    "reason",
                ]
            )
        else:
            frame = self._score(frame)
        frame.to_csv(self.output_dir / "relative_strength_rank.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame)
        get_store().append_generic_frame("relative_strength_rank", "relative_strength_rank.csv", frame)
        return frame

    def _raw_row(
        self,
        symbol: str,
        frame: pd.DataFrame,
        market_data: dict[str, pd.DataFrame],
    ) -> dict[str, object] | None:
        clean = frame.dropna().sort_index()
        if len(clean) < 130 or symbol in set(getattr(self.config, "watch_only_symbols", [])):
            return None
        close = clean["close"].astype(float)
        spy_close = _aligned_close(market_data.get("SPY"), clean.index[-1])
        spy_return_20d = _period_return(spy_close, 20)
        spy_return_60d = _period_return(spy_close, 60)
        return_20d = _period_return(close, 20)
        return_60d = _period_return(close, 60)
        return_120d = _period_return(close, 120)
        volatility_20d = float(close.pct_change().rolling(20).std().iloc[-1] * (252**0.5))
        latest = clean.iloc[-1]
        distance_fast_ma = float(latest.get("distance_fast_ma", 0.0))
        rsi = float(latest.get("rsi", latest.get("rsi14", 0.0)))
        trend_up = bool(latest.get("trend_up", False))
        above_fast_ma = bool(latest.get("above_fast_ma", False))
        return {
            "time": pd.Timestamp.now(),
            "symbol": symbol,
            "latest_date": pd.Timestamp(clean.index[-1]).date().isoformat(),
            "close": float(close.iloc[-1]),
            "return_20d": return_20d,
            "return_60d": return_60d,
            "return_120d": return_120d,
            "relative_spy_20d": return_20d - spy_return_20d,
            "relative_spy_60d": return_60d - spy_return_60d,
            "volatility_20d": volatility_20d,
            "distance_fast_ma": distance_fast_ma,
            "rsi": rsi,
            "trend_up": trend_up,
            "above_fast_ma": above_fast_ma,
        }

    def _score(self, frame: pd.DataFrame) -> pd.DataFrame:
        scored = frame.copy()
        scored["momentum_rank"] = _pct_rank(scored["return_20d"]) * 0.40 + _pct_rank(scored["return_60d"]) * 0.35 + _pct_rank(scored["return_120d"]) * 0.25
        scored["relative_rank"] = _pct_rank(scored["relative_spy_20d"]) * 0.55 + _pct_rank(scored["relative_spy_60d"]) * 0.45
        scored["volatility_rank"] = 1.0 - _pct_rank(scored["volatility_20d"])
        scored["trend_score"] = scored["trend_up"].astype(float) * 0.55 + scored["above_fast_ma"].astype(float) * 0.45
        scored["pullback_score"] = scored["distance_fast_ma"].apply(_pullback_score)
        scored["rsi_score"] = scored["rsi"].apply(_rsi_score)
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
        scored["reason"] = scored.apply(
            lambda row: (
                f"rank={int(row['rank'])}; score={row['relative_strength_score']:.2f}; "
                f"20d={row['return_20d']:.2%}; rel_spy_20d={row['relative_spy_20d']:.2%}; "
                f"vol={row['volatility_20d']:.2%}"
            ),
            axis=1,
        )
        columns = [
            "time",
            "symbol",
            "rank",
            "relative_strength_score",
            "status",
            "reason",
            "latest_date",
            "close",
            "return_20d",
            "return_60d",
            "return_120d",
            "relative_spy_20d",
            "relative_spy_60d",
            "volatility_20d",
            "distance_fast_ma",
            "rsi",
            "trend_up",
            "above_fast_ma",
        ]
        return scored[columns]

    def _write_report(self, frame: pd.DataFrame) -> None:
        lines = [
            "# Relative Strength Rank Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "| rank | symbol | score | status | return_20d | relative_spy_20d | volatility_20d |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in frame.to_dict(orient="records"):
            lines.append(
                f"| {row.get('rank', '')} | {row.get('symbol', '')} | "
                f"{float(row.get('relative_strength_score', 0.0)):.2f} | {row.get('status', '')} | "
                f"{float(row.get('return_20d', 0.0)):.2%} | "
                f"{float(row.get('relative_spy_20d', 0.0)):.2%} | "
                f"{float(row.get('volatility_20d', 0.0)):.2%} |"
            )
        (self.output_dir / "relative_strength_report.md").write_text("\n".join(lines), encoding="utf-8")


def _aligned_close(frame: pd.DataFrame | None, latest_index) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    clean = frame.dropna().sort_index()
    return clean.loc[clean.index <= latest_index, "close"].astype(float)


def _period_return(close: pd.Series, periods: int) -> float:
    if len(close) <= periods:
        return 0.0
    base = float(close.iloc[-periods - 1])
    if base == 0:
        return 0.0
    return float(close.iloc[-1] / base - 1)


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
