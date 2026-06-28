from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import LocalPaperConfig
from .database import get_store
from .strategy import evaluate_buy_signal, signal_metric_snapshot


class CandidateRankReporter:
    """生成候选股票排行榜和为什么没交易报告。"""

    def __init__(self, config: LocalPaperConfig | None = None, output_dir: Path | None = None) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir or self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        market_data: dict[str, pd.DataFrame],
        decisions: Iterable[object],
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        decision_frame = self._decision_frame(decisions)
        relative_strength = self._lookup("relative_strength_rank.csv", "symbol")
        universe = self._lookup("universe_filter.csv", "symbol")
        factor_latest = self._factor_lookup()

        rows = []
        for symbol in self.config.symbols:
            frame = market_data.get(symbol)
            if frame is None or frame.empty:
                continue
            clean = frame.dropna().sort_index()
            if clean.empty:
                continue
            latest = clean.iloc[-1]
            metrics = signal_metric_snapshot(latest)
            evaluation = evaluate_buy_signal(
                latest,
                rsi_limit=self.config.rsi_limit,
                enabled_strategies=self.config.enabled_buy_strategies,
                trend_min_rsi=self.config.trend_min_rsi,
                trend_volume_ratio=self.config.trend_volume_ratio,
                trend_max_distance_fast_ma=self.config.trend_max_distance_fast_ma,
                trend_min_return_5d=self.config.trend_min_return_5d,
            )
            row = self._candidate_row(
                symbol=symbol,
                latest_date=pd.Timestamp(clean.index[-1]).date().isoformat(),
                metrics=metrics,
                evaluation=evaluation,
                relative_strength=relative_strength.get(symbol, {}),
                universe=universe.get(symbol, {}),
                factor=factor_latest.get(symbol, {}),
                decision=self._latest_decision(decision_frame, symbol),
            )
            rows.append(row)

        ranking = pd.DataFrame(rows)
        if not ranking.empty:
            ranking = ranking.sort_values(
                ["candidate_score", "technical_score", "relative_strength_score", "factor_percentile"],
                ascending=[False, False, False, False],
            ).reset_index(drop=True)
            ranking["rank"] = ranking.index + 1
            ordered = [
                "time",
                "latest_date",
                "rank",
                "symbol",
                "candidate_score",
                "readiness",
                "action_hint",
                "blockers",
                "strategy_name",
                "technical_score",
                "technical_buy_met",
                "relative_strength_rank",
                "relative_strength_score",
                "relative_strength_status",
                "factor_percentile",
                "factor_signal",
                "universe_passed",
                "decision_signal",
                "decision_reject_reason",
                "close",
                "ma_gap_pct",
                "rsi",
                "volume_ratio",
                "distance_fast_ma",
                "return_5d",
            ]
            ranking = ranking[ordered]
        else:
            ranking = pd.DataFrame(columns=self._ranking_columns())

        summary = self._summary(ranking, decision_frame)
        self._write_outputs(ranking, summary)
        return ranking, summary

    def _candidate_row(
        self,
        symbol: str,
        latest_date: str,
        metrics: dict[str, object],
        evaluation,
        relative_strength: dict[str, object],
        universe: dict[str, object],
        factor: dict[str, object],
        decision: dict[str, object],
    ) -> dict[str, object]:
        technical_score = float(getattr(evaluation, "score", 0.0))
        rs_score = _number(relative_strength.get("relative_strength_score"), 0.0)
        rs_rank = _number(relative_strength.get("rank"), 999.0)
        factor_percentile = _number(factor.get("factor_percentile"), 0.5)
        risk_quality = self._risk_quality(metrics)
        universe_passed = _bool(universe.get("tradable_passed"), default=True)
        decision_reject_reason = str(decision.get("reject_reason", "") or "")
        blockers = self._blockers(
            symbol=symbol,
            technical_buy_met=bool(getattr(evaluation, "should_buy", False)),
            evaluation_reason=str(getattr(evaluation, "reason", "") or ""),
            relative_strength=relative_strength,
            universe=universe,
            universe_passed=universe_passed,
            decision_reject_reason=decision_reject_reason,
        )
        score = (
            technical_score * 0.45
            + rs_score * 0.25
            + factor_percentile * 100 * 0.20
            + risk_quality * 100 * 0.10
        )
        if not universe_passed:
            score *= 0.25
        if symbol in set(getattr(self.config, "watch_only_symbols", [])):
            score *= 0.10

        readiness = self._readiness(score, blockers, bool(getattr(evaluation, "should_buy", False)), universe_passed)
        return {
            "time": pd.Timestamp.now(),
            "latest_date": latest_date,
            "symbol": symbol,
            "candidate_score": round(float(score), 2),
            "readiness": readiness,
            "action_hint": self._action_hint(readiness),
            "blockers": "；".join(blockers) if blockers else "none",
            "strategy_name": str(getattr(evaluation, "strategy_name", "")),
            "technical_score": round(technical_score, 2),
            "technical_buy_met": bool(getattr(evaluation, "should_buy", False)),
            "relative_strength_rank": int(rs_rank) if rs_rank < 999 else "",
            "relative_strength_score": round(rs_score, 2),
            "relative_strength_status": str(relative_strength.get("status", "NO_DATA") or "NO_DATA"),
            "factor_percentile": round(factor_percentile, 4),
            "factor_signal": str(factor.get("factor_signal", "NO_DATA")),
            "universe_passed": universe_passed,
            "decision_signal": str(decision.get("signal_type", "")),
            "decision_reject_reason": decision_reject_reason,
            "close": round(_number(metrics.get("close"), 0.0), 4),
            "ma_gap_pct": round(_number(metrics.get("ma_gap_pct"), 0.0), 6),
            "rsi": round(_number(metrics.get("rsi"), 0.0), 2),
            "volume_ratio": round(_number(metrics.get("volume_ratio"), 0.0), 4),
            "distance_fast_ma": round(_number(metrics.get("distance_fast_ma"), 0.0), 6),
            "return_5d": round(_number(metrics.get("return_5d"), 0.0), 6),
        }

    def _blockers(
        self,
        symbol: str,
        technical_buy_met: bool,
        evaluation_reason: str,
        relative_strength: dict[str, object],
        universe: dict[str, object],
        universe_passed: bool,
        decision_reject_reason: str,
    ) -> list[str]:
        blockers = []
        if symbol in set(getattr(self.config, "watch_only_symbols", [])):
            blockers.append("观察标的")
        if evaluation_reason and not technical_buy_met:
            blockers.append(evaluation_reason)
        if not universe_passed:
            blockers.append(str(universe.get("reject_reason", "股票池过滤未通过")))
        rs_status = str(relative_strength.get("status", "NO_DATA") or "NO_DATA")
        if rs_status not in {"PASS", ""}:
            blockers.append(f"相对强弱未通过: {rs_status}")
        if decision_reject_reason:
            blockers.append(decision_reject_reason)
        return _dedupe(blockers)

    def _summary(self, ranking: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
        orders_generated = int(decisions.get("order_submitted", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not decisions.empty else 0
        buy_signals = int(decisions.get("signal_type", pd.Series(dtype=str)).astype(str).eq("BUY").sum()) if not decisions.empty else 0
        top = ranking.iloc[0].to_dict() if not ranking.empty else {}
        blockers = []
        if not ranking.empty and "blockers" in ranking.columns:
            for value in ranking["blockers"].astype(str).tolist():
                if value and value != "none":
                    blockers.extend(item.strip() for item in value.split("；") if item.strip())
        common_blocker = Counter(blockers).most_common(1)[0][0] if blockers else "none"
        if orders_generated > 0:
            status = "TRADED"
            message = f"本次运行已产生 {orders_generated} 个模拟订单"
        elif not ranking.empty:
            status = "NO_TRADE_EXPLAINED"
            message = f"本次无交易；最高候选 {top.get('symbol', '')} 分数 {float(top.get('candidate_score', 0.0)):.2f}"
        else:
            status = "NO_CANDIDATES"
            message = "本次没有可排名候选，优先检查行情缓存和股票池过滤"
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "status": status,
                    "message": message,
                    "ranked_count": int(len(ranking)),
                    "orders_generated": orders_generated,
                    "buy_signal_count": buy_signals,
                    "top_symbol": str(top.get("symbol", "")),
                    "top_candidate_score": float(top.get("candidate_score", 0.0) or 0.0),
                    "top_readiness": str(top.get("readiness", "")),
                    "common_blocker": common_blocker,
                }
            ]
        )

    def _write_outputs(self, ranking: pd.DataFrame, summary: pd.DataFrame) -> None:
        ranking.to_csv(self.output_dir / "candidate_rank.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "no_trade_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(ranking, summary)
        get_store().append_generic_frame("candidate_rank", "candidate_rank.csv", ranking)
        get_store().append_generic_frame("no_trade_summary", "no_trade_summary.csv", summary)

    def _write_report(self, ranking: pd.DataFrame, summary: pd.DataFrame) -> None:
        row = summary.iloc[-1] if not summary.empty else {}
        lines = [
            "# No-Trade And Candidate Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            f"Status: {_get(row, 'status', 'UNKNOWN')}",
            f"Message: {_get(row, 'message', '')}",
            "",
            "This report is for local paper trading analysis only. It does not place orders.",
            "",
            "## Top Candidates",
            "",
            "| rank | symbol | score | readiness | hint | blockers |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        if ranking.empty:
            lines.append("|  |  |  |  |  | No candidates. |")
        else:
            for item in ranking.head(12).to_dict(orient="records"):
                lines.append(
                    f"| {item.get('rank', '')} | {item.get('symbol', '')} | "
                    f"{float(item.get('candidate_score', 0.0)):.2f} | {item.get('readiness', '')} | "
                    f"{item.get('action_hint', '')} | {item.get('blockers', '')} |"
                )
        lines.extend(
            [
                "",
                "## Main Blocker",
                "",
                f"- {_get(row, 'common_blocker', 'none')}",
                "",
                "## How To Read",
                "",
                "- READY means the symbol is closest to being tradable, but normal risk rules still apply.",
                "- WATCH means it has some strength but still needs confirmation.",
                "- BLOCKED means one or more safety, universe, or signal filters failed.",
            ]
        )
        (self.output_dir / "no_trade_report.md").write_text("\n".join(lines), encoding="utf-8")

    def _factor_lookup(self) -> dict[str, dict[str, object]]:
        frame = self._read_csv("factor_lab_latest_rank.csv")
        if frame.empty:
            return {}
        grouped = []
        for symbol, group in frame.groupby("symbol"):
            percentiles = pd.to_numeric(group.get("factor_percentile", pd.Series(dtype=float)), errors="coerce").dropna()
            scores = pd.to_numeric(group.get("factor_score", pd.Series(dtype=float)), errors="coerce").dropna()
            best = group.sort_values("factor_rank").iloc[0].to_dict() if "factor_rank" in group.columns else group.iloc[0].to_dict()
            grouped.append(
                (
                    str(symbol),
                    {
                        "factor_percentile": float(percentiles.mean()) if not percentiles.empty else 0.5,
                        "factor_score": float(scores.max()) if not scores.empty else 0.0,
                        "factor_signal": f"{best.get('factor_name', 'none')} rank={best.get('factor_rank', '')}",
                    },
                )
            )
        return dict(grouped)

    def _lookup(self, filename: str, key: str) -> dict[str, dict[str, object]]:
        frame = self._read_csv(filename)
        if frame.empty or key not in frame.columns:
            return {}
        return {str(row[key]): row.to_dict() for _, row in frame.iterrows() if str(row.get(key, "")).strip()}

    def _read_csv(self, filename: str) -> pd.DataFrame:
        path = self.output_dir / filename
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    @staticmethod
    def _latest_decision(decisions: pd.DataFrame, symbol: str) -> dict[str, object]:
        if decisions.empty or "symbol" not in decisions.columns:
            return {}
        selected = decisions[decisions["symbol"].astype(str) == symbol]
        if selected.empty:
            return {}
        return selected.iloc[-1].to_dict()

    @staticmethod
    def _decision_frame(decisions: Iterable[object]) -> pd.DataFrame:
        rows = []
        for decision in decisions:
            if isinstance(decision, dict):
                rows.append(decision)
            else:
                rows.append({key: getattr(decision, key) for key in dir(decision) if not key.startswith("_") and not callable(getattr(decision, key))})
        return pd.DataFrame(rows)

    @staticmethod
    def _risk_quality(metrics: dict[str, object]) -> float:
        rsi = _number(metrics.get("rsi"), 0.0)
        distance = abs(_number(metrics.get("distance_fast_ma"), 0.0))
        volume_ratio = _number(metrics.get("volume_ratio"), 0.0)
        rsi_score = 1.0 if 45 <= rsi <= 65 else 0.6 if 38 <= rsi < 70 else 0.2
        distance_score = 1.0 if distance <= 0.05 else 0.6 if distance <= 0.10 else 0.2
        volume_score = min(max(volume_ratio / 1.2, 0.0), 1.0)
        return float(rsi_score * 0.35 + distance_score * 0.35 + volume_score * 0.30)

    @staticmethod
    def _readiness(score: float, blockers: list[str], technical_buy_met: bool, universe_passed: bool) -> str:
        if technical_buy_met and universe_passed and not blockers:
            return "READY"
        if score >= 70 and universe_passed:
            return "NEAR_READY"
        if score >= 50 and universe_passed:
            return "WATCH"
        return "BLOCKED"

    @staticmethod
    def _action_hint(readiness: str) -> str:
        if readiness == "READY":
            return "Eligible if risk and one-order rules allow"
        if readiness == "NEAR_READY":
            return "Watch next session for final confirmation"
        if readiness == "WATCH":
            return "Keep monitoring"
        return "Do not buy"

    @staticmethod
    def _ranking_columns() -> list[str]:
        return [
            "time",
            "latest_date",
            "rank",
            "symbol",
            "candidate_score",
            "readiness",
            "action_hint",
            "blockers",
            "strategy_name",
            "technical_score",
            "technical_buy_met",
            "relative_strength_rank",
            "relative_strength_score",
            "relative_strength_status",
            "factor_percentile",
            "factor_signal",
            "universe_passed",
            "decision_signal",
            "decision_reject_reason",
            "close",
            "ma_gap_pct",
            "rsi",
            "volume_ratio",
            "distance_fast_ma",
            "return_5d",
        ]


def _number(value: object, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _get(row: object, key: str, default: object) -> object:
    try:
        value = row[key]
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default
