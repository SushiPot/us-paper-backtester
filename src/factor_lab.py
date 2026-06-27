from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import LocalPaperConfig
from .database import get_store


@dataclass(frozen=True)
class FactorDefinition:
    """轻量因子定义。direction=1 表示数值越大越好，-1 表示越小越好。"""

    name: str
    description: str
    direction: int = 1


FACTOR_DEFINITIONS = [
    FactorDefinition("momentum_20d", "20 日价格动量"),
    FactorDefinition("risk_adjusted_momentum_20d", "20 日动量除以 20 日波动率"),
    FactorDefinition("trend_ma_gap", "MA20 相对 MA60 的趋势强度"),
    FactorDefinition("volume_confirmed_momentum", "成交量确认的 20 日动量"),
    FactorDefinition("price_volume_corr_20d", "20 日价格收益与成交量变化相关性"),
    FactorDefinition("low_volatility", "低波动防守因子"),
    FactorDefinition("balanced_rsi", "RSI 靠近中性偏强区间的得分"),
    FactorDefinition("breakout_60d", "距离 60 日高点的突破强度"),
]


class FactorLabAnalyzer:
    """借鉴因子研究平台思想的轻量美股因子实验室。

    这里不复制外部项目代码，只实现本项目需要的安全子集：
    因子计算、去极值、截面标准化、IC/Rank IC、分组收益和最新排名。
    """

    def __init__(
        self,
        config: LocalPaperConfig | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir or self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.group_count = 3
        self.min_symbols_per_day = 3

    def run(self, market_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        panel = self._build_panel(market_data)
        if panel.empty:
            summary = self._empty_summary("NO_DATA", "No factor panel could be built.")
            self._write_outputs(summary, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
            return summary

        factor_panel = self._prepare_factor_panel(panel)
        if factor_panel.empty:
            summary = self._empty_summary("NO_FACTORS", "No valid factor values after cleaning.")
            self._write_outputs(summary, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
            return summary

        score_rows: list[dict[str, object]] = []
        daily_rows: list[dict[str, object]] = []
        group_rows: list[dict[str, object]] = []
        horizons = sorted({int(horizon) for horizon in self.config.signal_eval_horizons if int(horizon) > 0})

        for definition in FACTOR_DEFINITIONS:
            if definition.name not in factor_panel.columns:
                continue
            for horizon in horizons:
                score, daily, group_returns = self._evaluate_factor(factor_panel, definition, horizon)
                score_rows.append(score)
                daily_rows.extend(daily)
                group_rows.extend(group_returns)

        scores = pd.DataFrame(score_rows)
        daily_ic = pd.DataFrame(daily_rows)
        group_detail = pd.DataFrame(group_rows)
        summary = self._summary(scores)
        latest = self._latest_rank(factor_panel, summary)
        self._write_outputs(summary, latest, daily_ic, group_detail)
        return summary

    def _build_panel(self, market_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        rows = []
        watch_only = set(self.config.watch_only_symbols)
        for symbol, frame in market_data.items():
            if symbol in watch_only:
                continue
            clean = frame.dropna(subset=["close"]).sort_index().copy()
            if len(clean) < 90:
                continue
            close = clean["close"].astype(float)
            high = clean.get("high", close).astype(float)
            low = clean.get("low", close).astype(float)
            volume = clean.get("volume", pd.Series(0.0, index=clean.index)).astype(float)
            returns = close.pct_change()
            ma20 = close.rolling(20).mean()
            ma60 = close.rolling(60).mean()
            volume_ma20 = volume.rolling(20).mean()
            volatility_20d = returns.rolling(20).std(ddof=0) * np.sqrt(252)
            volume_change = volume.replace(0, np.nan).pct_change()
            high_60d = high.rolling(60).max()

            symbol_frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(clean.index),
                    "symbol": symbol,
                    "close": close,
                    "volume": volume,
                    "momentum_20d": close.pct_change(20),
                    "risk_adjusted_momentum_20d": close.pct_change(20) / volatility_20d.replace(0, np.nan),
                    "trend_ma_gap": ma20 / ma60 - 1,
                    "volume_confirmed_momentum": close.pct_change(20)
                    * np.log1p((volume / volume_ma20.replace(0, np.nan)).clip(lower=0, upper=5)),
                    "price_volume_corr_20d": returns.rolling(20, min_periods=10).corr(volume_change),
                    "low_volatility": -volatility_20d,
                    "balanced_rsi": -((clean.get("rsi", pd.Series(np.nan, index=clean.index)).astype(float) - 55).abs() / 100),
                    "breakout_60d": close / high_60d.replace(0, np.nan) - 1,
                    "intraday_range_20d": ((high - low) / close.replace(0, np.nan)).rolling(20).mean(),
                }
            )
            for horizon in self.config.signal_eval_horizons:
                horizon_int = int(horizon)
                if horizon_int > 0:
                    symbol_frame[f"future_return_{horizon_int}d"] = close.shift(-horizon_int) / close - 1
            rows.append(symbol_frame)

        if not rows:
            return pd.DataFrame()
        panel = pd.concat(rows, ignore_index=True)
        panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
        return panel.replace([np.inf, -np.inf], np.nan)

    def _prepare_factor_panel(self, panel: pd.DataFrame) -> pd.DataFrame:
        prepared = panel.copy()
        for definition in FACTOR_DEFINITIONS:
            if definition.name not in prepared.columns:
                continue
            adjusted = prepared[definition.name].astype(float) * definition.direction
            prepared[f"{definition.name}_raw"] = prepared[definition.name]
            prepared[definition.name] = adjusted
            prepared[f"{definition.name}_winsorized"] = adjusted.groupby(prepared["date"]).transform(_winsorize)
            prepared[f"{definition.name}_zscore"] = prepared[f"{definition.name}_winsorized"].groupby(prepared["date"]).transform(_zscore)
        return prepared

    def _evaluate_factor(
        self,
        panel: pd.DataFrame,
        definition: FactorDefinition,
        horizon: int,
    ) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
        value_column = f"{definition.name}_zscore"
        return_column = f"future_return_{horizon}d"
        usable = panel[["date", "symbol", value_column, return_column]].dropna().copy()
        usable = usable.rename(columns={value_column: "factor_value", return_column: "future_return"})
        sample_counts = usable.groupby("date")["symbol"].transform("count")
        usable = usable[sample_counts >= self.min_symbols_per_day].copy()

        if usable.empty:
            return self._empty_score(definition, horizon, "NO_VALID_ROWS"), [], []

        usable["factor_value"] = usable["factor_value"].astype(float)
        usable["future_return"] = usable["future_return"].astype(float)
        usable["factor_rank"] = usable.groupby("date")["factor_value"].rank(method="average")
        usable["return_rank"] = usable.groupby("date")["future_return"].rank(method="average")

        daily = pd.DataFrame(
            {
                "sample_count": usable.groupby("date")["symbol"].size(),
                "ic": _grouped_corr(usable, "date", "factor_value", "future_return"),
                "rank_ic": _grouped_corr(usable, "date", "factor_rank", "return_rank"),
            }
        ).reset_index()
        now = pd.Timestamp.now()
        daily.insert(0, "time", now)
        daily.insert(1, "factor_name", definition.name)
        daily.insert(2, "horizon_days", horizon)
        daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")

        group_counts = usable.groupby("date")["factor_value"].agg(
            lambda values: min(self.group_count, values.nunique(), len(values))
        )
        usable = usable.join(group_counts.rename("available_groups"), on="date")
        usable = usable[usable["available_groups"] >= 2].copy()
        if usable.empty:
            return self._empty_score(definition, horizon, "NO_GROUP_ROWS"), daily.to_dict(orient="records"), []

        usable["factor_rank_pct"] = usable.groupby("date")["factor_value"].rank(method="first", pct=True)
        usable["factor_group"] = (
            np.ceil(usable["factor_rank_pct"] * usable["available_groups"])
            .clip(lower=1)
            .astype(int)
        )
        group_detail = (
            usable.groupby(["date", "factor_group"], as_index=False)
            .agg(member_count=("future_return", "size"), avg_future_return=("future_return", "mean"))
            .sort_values(["date", "factor_group"])
        )
        group_detail.insert(0, "time", now)
        group_detail.insert(1, "factor_name", definition.name)
        group_detail.insert(2, "horizon_days", horizon)
        group_detail["date"] = pd.to_datetime(group_detail["date"]).dt.strftime("%Y-%m-%d")
        top_return, bottom_return, long_short_return, top_win_rate, monotonicity = self._group_metrics(group_detail)
        rank_ic_mean = float(daily["rank_ic"].dropna().mean()) if not daily.empty else 0.0
        ic_mean = float(daily["ic"].dropna().mean()) if not daily.empty else 0.0
        ic_std = float(daily["ic"].dropna().std(ddof=0)) if not daily.empty else 0.0
        rank_ic_positive_rate = float((daily["rank_ic"].dropna() > 0).mean()) if not daily.empty else 0.0
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0.0
        score = self._factor_score(
            sample_count=len(usable),
            valid_dates=daily["date"].nunique(),
            rank_ic_mean=rank_ic_mean,
            long_short_return=long_short_return,
            top_win_rate=top_win_rate,
            monotonicity=monotonicity,
        )
        status = self._status(len(usable), daily["date"].nunique(), rank_ic_mean, long_short_return, score)

        score_row = {
            "time": pd.Timestamp.now(),
            "factor_name": definition.name,
            "description": definition.description,
            "horizon_days": horizon,
            "sample_count": int(len(usable)),
            "valid_dates": int(daily["date"].nunique()),
            "group_count": self.group_count,
            "ic_mean": round(ic_mean, 6),
            "rank_ic_mean": round(rank_ic_mean, 6),
            "ic_std": round(ic_std, 6),
            "ic_ir": round(ic_ir, 6),
            "positive_rank_ic_rate": round(rank_ic_positive_rate, 6),
            "top_group_avg_return": round(top_return, 6),
            "bottom_group_avg_return": round(bottom_return, 6),
            "long_short_avg_return": round(long_short_return, 6),
            "top_group_win_rate": round(top_win_rate, 6),
            "monotonicity": round(monotonicity, 6),
            "factor_score": round(score, 2),
            "status": status,
            "reason": self._reason(rank_ic_mean, long_short_return, top_win_rate, monotonicity),
        }
        return score_row, daily.to_dict(orient="records"), group_detail.to_dict(orient="records")

    def _group_metrics(self, group_detail: pd.DataFrame) -> tuple[float, float, float, float, float]:
        if group_detail.empty:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        by_group = group_detail.groupby("factor_group")["avg_future_return"].mean()
        if by_group.empty:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        bottom_group = int(by_group.index.min())
        top_group = int(by_group.index.max())
        top_return = float(by_group.loc[top_group])
        bottom_return = float(by_group.loc[bottom_group])
        long_short_return = top_return - bottom_return
        top_rows = group_detail[group_detail["factor_group"] == top_group]
        top_win_rate = float((top_rows["avg_future_return"].astype(float) > 0).mean()) if not top_rows.empty else 0.0
        if len(by_group) >= 2:
            monotonicity = _safe_corr(pd.Series(by_group.index.astype(float), index=by_group.index), by_group.astype(float))
        else:
            monotonicity = 0.0
        return top_return, bottom_return, long_short_return, top_win_rate, monotonicity

    @staticmethod
    def _factor_score(
        sample_count: int,
        valid_dates: int,
        rank_ic_mean: float,
        long_short_return: float,
        top_win_rate: float,
        monotonicity: float,
    ) -> float:
        data_weight = min(sample_count / 600, 1.0) * min(valid_dates / 80, 1.0)
        ic_score = _clip((rank_ic_mean + 0.03) / 0.12) * 35
        spread_score = _clip((long_short_return + 0.005) / 0.035) * 30
        win_score = _clip(top_win_rate) * 20
        monotonic_score = _clip((monotonicity + 0.2) / 1.2) * 15
        return float((ic_score + spread_score + win_score + monotonic_score) * data_weight)

    @staticmethod
    def _status(sample_count: int, valid_dates: int, rank_ic_mean: float, long_short_return: float, score: float) -> str:
        if sample_count < 120 or valid_dates < 30:
            return "NEEDS_MORE_DATA"
        if score >= 70 and rank_ic_mean > 0 and long_short_return > 0:
            return "LEADING"
        if score >= 50 and (rank_ic_mean > 0 or long_short_return > 0):
            return "OBSERVE"
        return "WEAK"

    @staticmethod
    def _reason(rank_ic_mean: float, long_short_return: float, top_win_rate: float, monotonicity: float) -> str:
        return (
            f"rank_ic={rank_ic_mean:.4f}; long_short={long_short_return:.2%}; "
            f"top_win={top_win_rate:.1%}; monotonicity={monotonicity:.2f}"
        )

    def _summary(self, scores: pd.DataFrame) -> pd.DataFrame:
        if scores.empty:
            return self._empty_summary("NO_SCORES", "No factor score was generated.")
        summary = scores.sort_values(
            ["factor_score", "rank_ic_mean", "long_short_avg_return"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
        summary["rank"] = summary.index + 1
        return summary[
            [
                "time",
                "rank",
                "factor_name",
                "description",
                "horizon_days",
                "factor_score",
                "status",
                "sample_count",
                "valid_dates",
                "rank_ic_mean",
                "ic_mean",
                "ic_ir",
                "positive_rank_ic_rate",
                "top_group_avg_return",
                "bottom_group_avg_return",
                "long_short_avg_return",
                "top_group_win_rate",
                "monotonicity",
                "reason",
            ]
        ]

    def _latest_rank(self, panel: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
        if summary.empty or panel.empty:
            return pd.DataFrame()
        best_factors = summary.drop_duplicates("factor_name").head(5)["factor_name"].tolist()
        latest_date = panel["date"].max()
        latest = panel[panel["date"] == latest_date].copy()
        rows = []
        for factor_name in best_factors:
            value_column = f"{factor_name}_zscore"
            if value_column not in latest.columns:
                continue
            factor_rows = latest[["symbol", "date", value_column]].dropna().copy()
            if factor_rows.empty:
                continue
            factor_rows["factor_percentile"] = factor_rows[value_column].rank(pct=True)
            factor_rows = factor_rows.sort_values(value_column, ascending=False).reset_index(drop=True)
            factor_rows["factor_rank"] = factor_rows.index + 1
            leader_score = float(summary[summary["factor_name"] == factor_name].iloc[0]["factor_score"])
            for row in factor_rows.to_dict(orient="records"):
                rows.append(
                    {
                        "time": pd.Timestamp.now(),
                        "latest_date": pd.Timestamp(row["date"]).date().isoformat(),
                        "factor_name": factor_name,
                        "factor_score": round(leader_score, 2),
                        "symbol": row["symbol"],
                        "factor_rank": int(row["factor_rank"]),
                        "factor_percentile": round(float(row["factor_percentile"]), 6),
                        "factor_zscore": round(float(row[value_column]), 6),
                    }
                )
        return pd.DataFrame(rows)

    def _write_outputs(
        self,
        summary: pd.DataFrame,
        latest: pd.DataFrame,
        daily_ic: pd.DataFrame,
        group_detail: pd.DataFrame,
    ) -> None:
        summary.to_csv(self.output_dir / "factor_lab_summary.csv", index=False, encoding="utf-8-sig")
        latest.to_csv(self.output_dir / "factor_lab_latest_rank.csv", index=False, encoding="utf-8-sig")
        daily_ic.to_csv(self.output_dir / "factor_lab_daily_ic.csv", index=False, encoding="utf-8-sig")
        group_detail.to_csv(self.output_dir / "factor_lab_group_returns.csv", index=False, encoding="utf-8-sig")
        self._write_report(summary, latest)
        get_store().append_generic_frame("factor_lab_summary", "factor_lab_summary.csv", summary)
        get_store().append_generic_frame("factor_lab_latest_rank", "factor_lab_latest_rank.csv", latest)

    def _write_report(self, summary: pd.DataFrame, latest: pd.DataFrame) -> None:
        lines = [
            "# Factor Lab Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "This report evaluates factors before they are used for trading decisions. It is research-only and does not place orders.",
            "",
            "Method: winsorize by date, z-score by date, then evaluate IC, Rank IC, factor group returns, long-short spread, and monotonicity.",
            "",
        ]
        if summary.empty:
            lines.append("No factor results are available yet.")
        else:
            columns = [
                "rank",
                "factor_name",
                "horizon_days",
                "factor_score",
                "status",
                "rank_ic_mean",
                "long_short_avg_return",
                "top_group_win_rate",
                "monotonicity",
            ]
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in summary.head(12).to_dict(orient="records"):
                lines.append(
                    f"| {row.get('rank', '')} | {row.get('factor_name', '')} | {row.get('horizon_days', '')} | "
                    f"{float(row.get('factor_score', 0.0)):.2f} | {row.get('status', '')} | "
                    f"{float(row.get('rank_ic_mean', 0.0)):.4f} | "
                    f"{float(row.get('long_short_avg_return', 0.0)):.2%} | "
                    f"{float(row.get('top_group_win_rate', 0.0)):.1%} | "
                    f"{float(row.get('monotonicity', 0.0)):.2f} |"
                )
        if not latest.empty:
            lines.extend(["", "## Latest Factor Leaders", ""])
            for factor_name, group in latest.groupby("factor_name"):
                leaders = ", ".join(group.sort_values("factor_rank").head(3)["symbol"].astype(str).tolist())
                lines.append(f"- {factor_name}: {leaders}")
        (self.output_dir / "factor_lab_report.md").write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _empty_score(definition: FactorDefinition, horizon: int, status: str) -> dict[str, object]:
        return {
            "time": pd.Timestamp.now(),
            "factor_name": definition.name,
            "description": definition.description,
            "horizon_days": horizon,
            "sample_count": 0,
            "valid_dates": 0,
            "group_count": 0,
            "ic_mean": 0.0,
            "rank_ic_mean": 0.0,
            "ic_std": 0.0,
            "ic_ir": 0.0,
            "positive_rank_ic_rate": 0.0,
            "top_group_avg_return": 0.0,
            "bottom_group_avg_return": 0.0,
            "long_short_avg_return": 0.0,
            "top_group_win_rate": 0.0,
            "monotonicity": 0.0,
            "factor_score": 0.0,
            "status": status,
            "reason": status,
        }

    @staticmethod
    def _empty_summary(status: str, reason: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "rank": 0,
                    "factor_name": "none",
                    "description": reason,
                    "horizon_days": 0,
                    "factor_score": 0.0,
                    "status": status,
                    "sample_count": 0,
                    "valid_dates": 0,
                    "rank_ic_mean": 0.0,
                    "ic_mean": 0.0,
                    "ic_ir": 0.0,
                    "positive_rank_ic_rate": 0.0,
                    "top_group_avg_return": 0.0,
                    "bottom_group_avg_return": 0.0,
                    "long_short_avg_return": 0.0,
                    "top_group_win_rate": 0.0,
                    "monotonicity": 0.0,
                    "reason": reason,
                }
            ]
        )


def _winsorize(series: pd.Series) -> pd.Series:
    clean = series.astype(float)
    median = clean.median()
    mad = (clean - median).abs().median()
    if pd.notna(mad) and mad > 0:
        width = 3.0 * 1.4826 * mad
        return clean.clip(lower=median - width, upper=median + width)
    std = clean.std(ddof=0)
    mean = clean.mean()
    if pd.notna(std) and std > 0:
        return clean.clip(lower=mean - 3 * std, upper=mean + 3 * std)
    return clean


def _zscore(series: pd.Series) -> pd.Series:
    clean = series.astype(float)
    std = clean.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=clean.index)
    return (clean - clean.mean()) / std


def _grouped_corr(frame: pd.DataFrame, group_column: str, left_column: str, right_column: str) -> pd.Series:
    """用向量化方式计算每个日期组内的相关系数，避免大量小 group 循环。"""
    grouped = frame.groupby(group_column)
    left = frame[left_column].astype(float)
    right = frame[right_column].astype(float)
    left_centered = left - grouped[left_column].transform("mean")
    right_centered = right - grouped[right_column].transform("mean")
    group_key = frame[group_column]
    numerator = (left_centered * right_centered).groupby(group_key).sum()
    left_sum = (left_centered * left_centered).groupby(group_key).sum()
    right_sum = (right_centered * right_centered).groupby(group_key).sum()
    denominator = np.sqrt(left_sum * right_sum).replace(0, np.nan)
    return (numerator / denominator).replace([np.inf, -np.inf], np.nan)


def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    frame = pd.DataFrame({"left": left.astype(float), "right": right.astype(float)}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 3 or frame["left"].nunique() < 2 or frame["right"].nunique() < 2:
        return 0.0
    value = frame["left"].corr(frame["right"])
    if pd.isna(value):
        return 0.0
    return float(value)


def _clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))
