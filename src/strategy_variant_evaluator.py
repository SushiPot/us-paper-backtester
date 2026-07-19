from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .backtester import Backtester
from .config import BacktestConfig
from .database import get_store


@dataclass(frozen=True)
class StrategyVariant:
    """可比较的策略配置变体。"""

    name: str
    enabled_buy_strategies: list[str]
    trend_position_scale: float
    trend_volume_ratio: float
    trend_max_distance_fast_ma: float
    note: str


class StrategyVariantEvaluator:
    """自动比较多个策略变体，给自我优化报告提供依据。"""

    VARIANTS = [
        StrategyVariant("strict_only", ["strict_golden_cross"], 0.0, 1.00, 0.00, "只使用原始严格金叉"),
        StrategyVariant("trend_only", ["trend_follow"], 0.40, 0.80, 0.08, "只使用趋势确认"),
        StrategyVariant("default_blend", ["strict_golden_cross", "trend_follow"], 0.40, 0.80, 0.08, "当前默认组合"),
        StrategyVariant("conservative_blend", ["strict_golden_cross", "trend_follow"], 0.25, 0.90, 0.06, "更保守的趋势仓位和成交量过滤"),
    ]

    def __init__(self, base_config: BacktestConfig | None = None, output_dir: Path = Path("outputs")) -> None:
        self.base_config = base_config or BacktestConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        rows = []
        for variant in self.VARIANTS:
            variant_dir = self.output_dir / "strategy_variants" / variant.name
            config = BacktestConfig(
                symbols=self.base_config.symbols,
                watch_only_symbols=self.base_config.watch_only_symbols,
                required_symbols=self.base_config.required_symbols,
                start_date=self.base_config.start_date,
                end_date=self.base_config.end_date,
                initial_cash=self.base_config.initial_cash,
                fast_ma=self.base_config.fast_ma,
                slow_ma=self.base_config.slow_ma,
                rsi_period=self.base_config.rsi_period,
                rsi_limit=self.base_config.rsi_limit,
                enabled_buy_strategies=variant.enabled_buy_strategies,
                trend_min_rsi=self.base_config.trend_min_rsi,
                trend_volume_ratio=variant.trend_volume_ratio,
                trend_max_distance_fast_ma=variant.trend_max_distance_fast_ma,
                trend_min_return_5d=self.base_config.trend_min_return_5d,
                trend_position_scale=variant.trend_position_scale,
                max_position_pct=self.base_config.max_position_pct,
                special_max_position_pct=self.base_config.special_max_position_pct,
                max_positions=self.base_config.max_positions,
                stop_loss_pct=self.base_config.stop_loss_pct,
                take_profit_pct=self.base_config.take_profit_pct,
                max_holding_days=self.base_config.max_holding_days,
                daily_loss_limit_pct=self.base_config.daily_loss_limit_pct,
                max_account_drawdown_pct=self.base_config.max_account_drawdown_pct,
                output_dir=variant_dir,
                cache_dir=self.base_config.cache_dir,
                cache_max_age_hours=self.base_config.cache_max_age_hours,
                max_new_symbol_downloads_per_run=self.base_config.max_new_symbol_downloads_per_run,
                market_data_primary_source=self.base_config.market_data_primary_source,
                market_data_request_interval_seconds=self.base_config.market_data_request_interval_seconds,
                yfinance_timeout_seconds=self.base_config.yfinance_timeout_seconds,
                retry_count=self.base_config.retry_count,
                retry_wait_seconds=self.base_config.retry_wait_seconds,
            )
            report = Backtester(config).run()
            score = self._score(report.total_return, report.max_drawdown, report.sharpe_ratio, report.trade_count)
            rows.append(
                {
                    "variant": variant.name,
                    "enabled_buy_strategies": ",".join(variant.enabled_buy_strategies),
                    "trend_position_scale": variant.trend_position_scale,
                    "trend_volume_ratio": variant.trend_volume_ratio,
                    "trend_max_distance_fast_ma": variant.trend_max_distance_fast_ma,
                    "total_return": report.total_return,
                    "annual_return": report.annual_return,
                    "max_drawdown": report.max_drawdown,
                    "sharpe_ratio": report.sharpe_ratio,
                    "win_rate": report.win_rate,
                    "avg_profit_loss_ratio": report.avg_profit_loss_ratio,
                    "trade_count": report.trade_count,
                    "variant_score": score,
                    "note": variant.note,
                }
            )

        frame = pd.DataFrame(rows).sort_values(["variant_score", "sharpe_ratio"], ascending=[False, False])
        frame.to_csv(self.output_dir / "strategy_variant_scores.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame)
        get_store().append_generic_frame("strategy_variant_scores", "strategy_variant_scores.csv", frame)
        return frame

    @staticmethod
    def _score(total_return: float, max_drawdown: float, sharpe_ratio: float, trade_count: int) -> float:
        score = 50.0
        score += max(-20.0, min(30.0, total_return * 80.0))
        score += max(-20.0, min(25.0, sharpe_ratio * 18.0))
        score -= min(30.0, abs(min(max_drawdown, 0.0)) * 220.0)
        if trade_count < 10:
            score -= 12.0
        elif trade_count > 300:
            score -= 5.0
        return round(max(0.0, min(100.0, score)), 2)

    def _write_report(self, frame: pd.DataFrame) -> None:
        lines = [
            "# Strategy Variant Evaluation",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
        ]
        if frame.empty:
            lines.append("No strategy variants were evaluated.")
        else:
            best = frame.iloc[0]
            lines.extend(
                [
                    f"Best variant: **{best['variant']}**",
                    "",
                    f"- Score: {float(best['variant_score']):.2f}",
                    f"- Total return: {float(best['total_return']):.2%}",
                    f"- Max drawdown: {float(best['max_drawdown']):.2%}",
                    f"- Sharpe: {float(best['sharpe_ratio']):.2f}",
                    "",
                    "## Leaderboard",
                    "",
                ]
            )
            columns = ["variant", "variant_score", "total_return", "max_drawdown", "sharpe_ratio", "trade_count", "note"]
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in frame.to_dict(orient="records"):
                lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
        (self.output_dir / "strategy_variant_report.md").write_text("\n".join(lines), encoding="utf-8")
