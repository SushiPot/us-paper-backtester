from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BacktestConfig
from .data import MarketDataLoader
from .database import get_store
from .optimizer import OptimizationResult, ParameterOptimizer, StrategyParams


@dataclass(frozen=True)
class WalkForwardSummary:
    """滚动训练/验证摘要。"""

    windows: int
    positive_test_windows: int
    best_params_label: str
    avg_test_return: float
    avg_test_sharpe: float
    worst_test_drawdown: float
    stability_score: float
    recommended_params_label: str
    recommended_action: str


class WalkForwardValidator:
    """用过去窗口选参数，再用未来窗口验证，降低过拟合风险。"""

    def __init__(
        self,
        config: BacktestConfig | None = None,
        output_dir: Path = Path("outputs"),
        train_days: int = 756,
        test_days: int = 252,
        step_days: int = 126,
        max_params: int | None = 48,
    ) -> None:
        self.config = config or BacktestConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days
        self.max_params = max_params
        self.optimizer = ParameterOptimizer(self.config, output_dir)

    def run(self) -> WalkForwardSummary:
        raw_data = MarketDataLoader(self.config).download_all()
        raw_data = self._filter_usable_symbols(raw_data)
        if not raw_data:
            raise RuntimeError("walk-forward 验证没有可用行情数据")

        calendar = pd.DatetimeIndex(sorted(set().union(*(frame.index for frame in raw_data.values()))))
        calendar = calendar[calendar >= pd.Timestamp(self.config.start_date)]
        if len(calendar) < self.train_days + self.test_days:
            raise RuntimeError("walk-forward 验证需要更长历史数据")

        params_grid = self._reduced_grid()
        window_rows = []
        candidate_rows = []

        for window_id, (train_dates, test_dates) in enumerate(self._windows(calendar), start=1):
            train_data = self._slice_data(raw_data, train_dates[0], train_dates[-1])
            train_results = [self._simulate(train_data, params) for params in params_grid]
            train_results = [result for result in train_results if result.trade_count > 0]
            if not train_results:
                continue

            train_rank = sorted(train_results, key=self._rank_key, reverse=True)
            best_train = train_rank[0]
            best_params = self._params_by_label(params_grid)[best_train.params_label]
            test_data = self._slice_data(raw_data, test_dates[0], test_dates[-1])
            test_result = self._simulate(test_data, best_params)

            window_rows.append(
                {
                    "window_id": window_id,
                    "train_start": train_dates[0].date().isoformat(),
                    "train_end": train_dates[-1].date().isoformat(),
                    "test_start": test_dates[0].date().isoformat(),
                    "test_end": test_dates[-1].date().isoformat(),
                    "selected_params": best_train.params_label,
                    "train_total_return": best_train.total_return,
                    "train_sharpe": best_train.sharpe_ratio,
                    "train_max_drawdown": best_train.max_drawdown,
                    "train_trade_count": best_train.trade_count,
                    "test_total_return": test_result.total_return,
                    "test_sharpe": test_result.sharpe_ratio,
                    "test_max_drawdown": test_result.max_drawdown,
                    "test_trade_count": test_result.trade_count,
                    "test_win_rate": test_result.win_rate,
                }
            )
            for rank, result in enumerate(train_rank[:5], start=1):
                candidate_rows.append(
                    {
                        "window_id": window_id,
                        "rank": rank,
                        **result.__dict__,
                    }
                )

        if not window_rows:
            raise RuntimeError("walk-forward 没有生成有效验证窗口")

        results = pd.DataFrame(window_rows)
        candidates = pd.DataFrame(candidate_rows)
        summary = self._summarize(results)

        results.to_csv(self.output_dir / "walk_forward_results.csv", index=False, encoding="utf-8-sig")
        candidates.to_csv(self.output_dir / "walk_forward_top20.csv", index=False, encoding="utf-8-sig")
        summary_frame = pd.DataFrame([summary.__dict__])
        summary_frame.to_csv(self.output_dir / "walk_forward_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(summary, results)

        store = get_store()
        store.append_generic_frame("walk_forward_results", "walk_forward_results.csv", results)
        store.append_generic_frame("walk_forward_candidates", "walk_forward_top20.csv", candidates)
        store.append_generic_frame("walk_forward_summary", "walk_forward_summary.csv", summary_frame)
        return summary

    def _reduced_grid(self) -> list[StrategyParams]:
        params = self.optimizer._default_grid()
        if self.max_params is None or len(params) <= self.max_params:
            return params
        selected = []
        preferred = {
            (20, 60, 70.0, -0.08, 0.20, 30),
            (30, 60, 60.0, -0.05, 0.30, 30),
            (10, 50, 60.0, -0.05, 0.20, 20),
            (20, 120, 70.0, -0.08, 0.30, 30),
        }
        for params_item in params:
            key = (
                params_item.fast_ma,
                params_item.slow_ma,
                params_item.rsi_limit,
                params_item.stop_loss_pct,
                params_item.take_profit_pct,
                params_item.max_holding_days,
            )
            if key in preferred:
                selected.append(params_item)
        for index, params_item in enumerate(params):
            if len(selected) >= self.max_params:
                break
            if index % 2 == 0 and params_item not in selected:
                selected.append(params_item)
        return selected[: self.max_params]

    @staticmethod
    def _params_by_label(params_grid: list[StrategyParams]) -> dict[str, StrategyParams]:
        return {params.label: params for params in params_grid}

    def _simulate(self, raw_data: dict[str, pd.DataFrame], params: StrategyParams) -> OptimizationResult:
        data = {symbol: self.optimizer._add_indicators(frame, params) for symbol, frame in raw_data.items()}
        return self.optimizer._simulate(data, params)

    def _windows(self, calendar: pd.DatetimeIndex):
        start = 0
        while start + self.train_days + self.test_days <= len(calendar):
            train_dates = calendar[start : start + self.train_days]
            test_dates = calendar[start + self.train_days : start + self.train_days + self.test_days]
            yield train_dates, test_dates
            start += self.step_days

    @staticmethod
    def _slice_data(raw_data: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
        sliced = {}
        for symbol, frame in raw_data.items():
            subset = frame[(frame.index >= start) & (frame.index <= end)].copy()
            if not subset.empty:
                sliced[symbol] = subset
        return sliced

    def _filter_usable_symbols(self, raw_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        min_rows = self.train_days + self.test_days
        usable = {}
        skipped = []
        for symbol, frame in raw_data.items():
            if "close" not in frame.columns or len(frame.dropna(subset=["close"])) < min_rows:
                skipped.append(symbol)
                continue
            usable[symbol] = frame
        if skipped:
            print(f"[WARN] walk-forward 历史不足，跳过: {', '.join(skipped)}", flush=True)
        return usable

    @staticmethod
    def _rank_key(result: OptimizationResult) -> tuple[float, float, float, int]:
        drawdown_penalty = abs(min(result.max_drawdown, 0.0))
        return (
            result.sharpe_ratio,
            result.total_return,
            -drawdown_penalty,
            result.trade_count,
        )

    @staticmethod
    def _summarize(results: pd.DataFrame) -> WalkForwardSummary:
        positive_test_windows = int((results["test_total_return"] > 0).sum())
        avg_test_return = float(results["test_total_return"].mean())
        avg_test_sharpe = float(results["test_sharpe"].mean())
        worst_test_drawdown = float(results["test_max_drawdown"].min())
        positive_rate = positive_test_windows / max(len(results), 1)
        stability_score = 50.0
        stability_score += max(-25.0, min(25.0, avg_test_sharpe * 12.0))
        stability_score += max(-20.0, min(20.0, avg_test_return * 100.0))
        stability_score += max(-20.0, min(20.0, (positive_rate - 0.5) * 40.0))
        stability_score -= min(25.0, abs(min(worst_test_drawdown, 0.0)) * 120.0)
        stability_score = round(max(0.0, min(100.0, stability_score)), 2)

        best_params_label = (
            results.groupby("selected_params")["test_total_return"]
            .mean()
            .sort_values(ascending=False)
            .index[0]
        )
        if stability_score >= 70:
            action = "ALLOW_NORMAL_SIMULATION"
        elif stability_score >= 50:
            action = "REDUCED_SIZE_SIMULATION"
        else:
            action = "OBSERVE_ONLY"

        return WalkForwardSummary(
            windows=int(len(results)),
            positive_test_windows=positive_test_windows,
            best_params_label=str(best_params_label),
            avg_test_return=avg_test_return,
            avg_test_sharpe=avg_test_sharpe,
            worst_test_drawdown=worst_test_drawdown,
            stability_score=stability_score,
            recommended_params_label=str(best_params_label),
            recommended_action=action,
        )

    def _write_report(self, summary: WalkForwardSummary, results: pd.DataFrame) -> None:
        lines = [
            "# Walk-Forward Validation Report",
            "",
            f"- Windows: {summary.windows}",
            f"- Positive test windows: {summary.positive_test_windows}",
            f"- Average test return: {summary.avg_test_return:.2%}",
            f"- Average test Sharpe: {summary.avg_test_sharpe:.2f}",
            f"- Worst test drawdown: {summary.worst_test_drawdown:.2%}",
            f"- Stability score: {summary.stability_score:.2f}",
            f"- Recommended params: {summary.recommended_params_label}",
            f"- Recommended action: {summary.recommended_action}",
            "",
            "## Recent Windows",
            "",
        ]
        recent = results.tail(10)
        columns = list(recent.columns)
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for row in recent.to_dict(orient="records"):
            lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
        (self.output_dir / "walk_forward_report.md").write_text("\n".join(lines), encoding="utf-8")
