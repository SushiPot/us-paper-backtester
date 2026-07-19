from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BacktestConfig, LocalPaperConfig, build_market_data_config
from .data import MarketDataLoader
from .database import get_store


@dataclass(frozen=True)
class StrategyHealthSummary:
    """策略健康度摘要，用于长期观察模拟盘是否越来越可靠。"""

    overall_score: float
    performance_score: float
    risk_score: float
    signal_score: float
    data_score: float
    walk_forward_score: float
    health_status: str
    recommended_action: str
    reason: str


class StrategyHealthAnalyzer:
    """参考 QuantStats/pyfolio 风格指标，生成本项目自己的策略评分。"""

    def __init__(
        self,
        local_config: LocalPaperConfig | None = None,
        backtest_config: BacktestConfig | None = None,
    ) -> None:
        self.local_config = local_config or LocalPaperConfig()
        self.backtest_config = backtest_config or BacktestConfig()
        self.output_dir = self.local_config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> StrategyHealthSummary:
        account_history = _read_csv(self.output_dir / self.local_config.account_history_file)
        decisions = _read_csv(self.output_dir / self.local_config.decision_log_file)
        trades = _read_csv(self.output_dir / self.local_config.paper_trade_log_file)
        performance = _read_csv(self.output_dir / self.local_config.local_performance_metrics_file)
        walk_forward = _read_csv(self.output_dir / "walk_forward_summary.csv")
        market_regime = self._build_market_regime()

        equity = self._extract_equity(account_history)
        returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna() if len(equity) >= 2 else pd.Series(dtype=float)

        data_score, data_reason = self._score_data(equity, trades, market_regime)
        performance_score = self._score_performance(performance, returns)
        risk_score = self._score_risk(performance, returns)
        signal_score, signal_reason = self._score_signals(decisions)
        walk_forward_score, walk_forward_reason, walk_forward_action = self._score_walk_forward(walk_forward)

        overall_score = round(
            0.25 * performance_score
            + 0.25 * risk_score
            + 0.20 * signal_score
            + 0.15 * data_score
            + 0.15 * walk_forward_score,
            2,
        )
        status, action, reason = self._classify(
            overall_score,
            data_reason,
            signal_reason,
            walk_forward_reason,
            walk_forward_action,
            market_regime,
        )

        summary = StrategyHealthSummary(
            overall_score=overall_score,
            performance_score=round(performance_score, 2),
            risk_score=round(risk_score, 2),
            signal_score=round(signal_score, 2),
            data_score=round(data_score, 2),
            walk_forward_score=round(walk_forward_score, 2),
            health_status=status,
            recommended_action=action,
            reason=reason,
        )
        self._write_outputs(summary, market_regime)
        return summary

    def _build_market_regime(self) -> pd.DataFrame:
        data_config = build_market_data_config(self.backtest_config, symbols=["SPY", "QQQ"], output_dir=self.output_dir)
        raw_data = MarketDataLoader(data_config).download_all()
        rows = []
        for symbol, frame in raw_data.items():
            close = frame["close"].dropna() if "close" in frame.columns else pd.Series(dtype=float)
            if len(close) < 60:
                rows.append(
                    {
                        "symbol": symbol,
                        "regime": "INSUFFICIENT_DATA",
                        "last_close": 0.0,
                        "ma20": 0.0,
                        "ma60": 0.0,
                        "volatility_20d": 0.0,
                        "drawdown_60d": 0.0,
                    }
                )
                continue

            ma20 = float(close.tail(20).mean())
            ma60 = float(close.tail(60).mean())
            last_close = float(close.iloc[-1])
            returns = close.pct_change().dropna()
            volatility = float(returns.tail(20).std(ddof=0) * np.sqrt(252)) if len(returns) >= 20 else 0.0
            drawdown = float(last_close / close.tail(60).max() - 1)
            if last_close > ma60 and ma20 > ma60:
                regime = "BULLISH"
            elif last_close < ma60 and ma20 < ma60:
                regime = "BEARISH"
            else:
                regime = "NEUTRAL"
            if volatility > 0.35 or drawdown <= -0.10:
                regime = f"{regime}_HIGH_RISK"

            rows.append(
                {
                    "symbol": symbol,
                    "regime": regime,
                    "last_close": last_close,
                    "ma20": ma20,
                    "ma60": ma60,
                    "volatility_20d": volatility,
                    "drawdown_60d": drawdown,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _extract_equity(account_history: pd.DataFrame) -> pd.Series:
        if account_history.empty or "equity" not in account_history.columns:
            return pd.Series(dtype=float)
        if "market_date" in account_history.columns:
            index = pd.to_datetime(account_history["market_date"], errors="coerce")
        elif "time" in account_history.columns:
            index = pd.to_datetime(account_history["time"], errors="coerce")
        else:
            index = pd.RangeIndex(len(account_history))
        equity = pd.Series(account_history["equity"].astype(float).to_numpy(), index=index, name="equity")
        equity = equity[~pd.isna(equity.index)]
        return equity.groupby(equity.index).last().sort_index()

    @staticmethod
    def _score_data(equity: pd.Series, trades: pd.DataFrame, market_regime: pd.DataFrame) -> tuple[float, str]:
        score = 100.0
        reasons = []
        if len(equity) < 20:
            score -= 35
            reasons.append("资金曲线少于20个观测点")
        if trades.empty or len(trades) < 5:
            score -= 30
            reasons.append("虚拟成交少于5笔")
        if not market_regime.empty and (market_regime["regime"] == "INSUFFICIENT_DATA").any():
            score -= 15
            reasons.append("市场状态数据不足")
        return max(0.0, score), "；".join(reasons)

    @staticmethod
    def _score_performance(performance: pd.DataFrame, returns: pd.Series) -> float:
        if not performance.empty:
            row = performance.iloc[-1]
            sharpe = float(row.get("sharpe_ratio", 0.0))
            total_return = float(row.get("total_return", 0.0))
            positive_rate = float(row.get("positive_day_rate", 0.0))
        elif not returns.empty:
            sharpe = float(returns.mean() / returns.std(ddof=0) * np.sqrt(252)) if returns.std(ddof=0) > 0 else 0.0
            total_return = float((1 + returns).prod() - 1)
            positive_rate = float((returns > 0).mean())
        else:
            return 40.0

        score = 50.0
        score += max(-20.0, min(25.0, sharpe * 12.0))
        score += max(-15.0, min(20.0, total_return * 100.0))
        score += max(-10.0, min(10.0, (positive_rate - 0.50) * 50.0))
        return max(0.0, min(100.0, score))

    def _score_risk(self, performance: pd.DataFrame, returns: pd.Series) -> float:
        if not performance.empty:
            max_drawdown = float(performance.iloc[-1].get("max_drawdown", 0.0))
            annual_volatility = float(performance.iloc[-1].get("annual_volatility", 0.0))
        elif not returns.empty:
            equity = (1 + returns).cumprod()
            max_drawdown = float((equity / equity.cummax() - 1).min())
            annual_volatility = float(returns.std(ddof=0) * np.sqrt(252)) if returns.std(ddof=0) > 0 else 0.0
        else:
            return 65.0

        score = 100.0
        drawdown_limit = abs(self.local_config.max_account_drawdown_pct)
        if max_drawdown < 0:
            score -= min(60.0, abs(max_drawdown) / max(drawdown_limit, 0.01) * 35.0)
        if annual_volatility > 0.25:
            score -= min(25.0, (annual_volatility - 0.25) * 80.0)
        return max(0.0, min(100.0, score))

    @staticmethod
    def _score_signals(decisions: pd.DataFrame) -> tuple[float, str]:
        if decisions.empty:
            return 45.0, "暂无策略决策记录"

        recent = decisions.tail(100).copy()
        reject_column = "reject_reason" if "reject_reason" in recent.columns else "拒绝原因" if "拒绝原因" in recent.columns else None
        signal_column = "signal_type" if "signal_type" in recent.columns else "信号类型" if "信号类型" in recent.columns else None
        risk_column = "risk_passed" if "risk_passed" in recent.columns else "是否通过风控" if "是否通过风控" in recent.columns else None

        score = 80.0
        reasons = []
        if reject_column:
            rejects = recent[reject_column].fillna("").astype(str).str.len() > 0
            reject_rate = float(rejects.mean())
            score -= min(35.0, reject_rate * 50.0)
            if reject_rate > 0.20:
                reasons.append(f"近期拒绝率偏高: {reject_rate:.0%}")
        if signal_column:
            non_hold = ~recent[signal_column].astype(str).isin(["HOLD", "NONE"])
            if float(non_hold.mean()) < 0.03:
                score -= 8.0
                reasons.append("近期信号较少，继续观察")
        if risk_column:
            risk_passed = recent[risk_column].astype(str).str.lower().isin(["true", "1"])
            if float(risk_passed.mean()) < 0.80:
                score -= 15.0
                reasons.append("近期部分决策未通过风控")
        return max(0.0, min(100.0, score)), "；".join(reasons)

    @staticmethod
    def _score_walk_forward(walk_forward: pd.DataFrame) -> tuple[float, str, str]:
        if walk_forward.empty:
            return 50.0, "尚未运行 walk-forward 验证", ""
        row = walk_forward.iloc[-1]
        stability_score = float(row.get("stability_score", 0.0))
        action = str(row.get("recommended_action", ""))
        windows = int(float(row.get("windows", 0)))
        reasons = []
        if windows < 3:
            reasons.append("walk-forward 验证窗口少于3个")
        if action == "OBSERVE_ONLY":
            reasons.append("walk-forward 建议继续观察")
        return max(0.0, min(100.0, stability_score)), "；".join(reasons), action

    @staticmethod
    def _classify(
        overall_score: float,
        data_reason: str,
        signal_reason: str,
        walk_forward_reason: str,
        walk_forward_action: str,
        market_regime: pd.DataFrame,
    ) -> tuple[str, str, str]:
        regimes = set(market_regime["regime"].astype(str)) if not market_regime.empty else set()
        high_risk_market = any("HIGH_RISK" in regime or "BEARISH" in regime for regime in regimes)
        reasons = [reason for reason in [data_reason, signal_reason, walk_forward_reason] if reason]

        if data_reason:
            return "OBSERVATION", "OBSERVE_ONLY", "；".join(reasons)
        if walk_forward_action == "OBSERVE_ONLY":
            return "OBSERVATION", "OBSERVE_ONLY", "；".join(reasons)
        if high_risk_market:
            return "CAUTION", "REDUCED_SIZE_OR_PAUSE_BUYS", "市场状态偏高风险；" + "；".join(reasons)
        if overall_score >= 75:
            return "HEALTHY", "NORMAL_SIMULATION", "策略健康度良好"
        if overall_score >= 55:
            return "CAUTION", "REDUCED_SIZE", "策略健康度一般；" + "；".join(reasons)
        return "WEAK", "PAUSE_NEW_BUYS", "策略评分偏弱；" + "；".join(reasons)

    def _write_outputs(self, summary: StrategyHealthSummary, market_regime: pd.DataFrame) -> None:
        summary_frame = pd.DataFrame([summary.__dict__])
        summary_frame.insert(0, "time", pd.Timestamp.now())
        summary_frame.to_csv(self.output_dir / "strategy_health.csv", index=False, encoding="utf-8-sig")
        market_regime.to_csv(self.output_dir / "market_regime.csv", index=False, encoding="utf-8-sig")
        self._write_markdown(summary, market_regime)
        store = get_store()
        store.append_generic_frame("strategy_health", "strategy_health.csv", summary_frame)
        store.append_generic_frame("market_regime", "market_regime.csv", market_regime)

    def _write_markdown(self, summary: StrategyHealthSummary, market_regime: pd.DataFrame) -> None:
        lines = [
            "# Strategy Health Report",
            "",
            f"- Overall score: {summary.overall_score:.2f}",
            f"- Status: {summary.health_status}",
            f"- Recommended action: {summary.recommended_action}",
            f"- Reason: {summary.reason or 'No major warning'}",
            "",
            "## Score Breakdown",
            "",
            f"- Performance: {summary.performance_score:.2f}",
            f"- Risk: {summary.risk_score:.2f}",
            f"- Signals: {summary.signal_score:.2f}",
            f"- Data: {summary.data_score:.2f}",
            f"- Walk-forward: {summary.walk_forward_score:.2f}",
            "",
            "## Market Regime",
            "",
        ]
        if market_regime.empty:
            lines.append("No market regime data.")
        else:
            columns = list(market_regime.columns)
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in market_regime.to_dict(orient="records"):
                values = [str(row.get(column, "")) for column in columns]
                lines.append("| " + " | ".join(values) + " |")
        (self.output_dir / "strategy_health_report.md").write_text("\n".join(lines), encoding="utf-8")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
