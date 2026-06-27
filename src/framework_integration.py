from __future__ import annotations

from pathlib import Path

import pandas as pd

from .database import get_store


FRAMEWORK_ROWS = [
    {
        "name": "Qlib",
        "repo": "microsoft/qlib",
        "asset_focus": "stocks, factors, ML research",
        "crypto_exposure": "none",
        "integration_level": "RESEARCH_PROCESS_REFERENCE",
        "use_now": "Factor pipeline discipline, label evaluation, train/test separation",
        "avoid_now": "Heavy ML stack, reinforcement learning, auto-trading decisions",
        "priority": 1,
        "reason": "高星项目里最适合借鉴研究流程；当前先吸收数据/标签/验证思想。",
    },
    {
        "name": "NautilusTrader",
        "repo": "nautechsystems/nautilus_trader",
        "asset_focus": "multi-asset event-driven trading",
        "crypto_exposure": "available but avoid",
        "integration_level": "EVENT_ENGINE_REFERENCE",
        "use_now": "Deterministic event model, order/fill/risk boundaries, durable logs",
        "avoid_now": "Gateway integration, crypto modules, production engine migration",
        "priority": 2,
        "reason": "适合学习长期运行系统的事件边界，但不适合直接接入真实账户。",
    },
    {
        "name": "QuantConnect LEAN",
        "repo": "QuantConnect/Lean",
        "asset_focus": "stocks, options, futures, forex",
        "crypto_exposure": "optional",
        "integration_level": "REFERENCE_ARCHITECTURE",
        "use_now": "Order model, portfolio model, security type separation, risk controls",
        "avoid_now": "Full engine migration; real broker integrations",
        "priority": 3,
        "reason": "最适合参考股票/期权统一回测和实盘架构，但体量很大，先借鉴设计。",
    },
    {
        "name": "backtrader",
        "repo": "mementum/backtrader",
        "asset_focus": "stocks, backtesting",
        "crypto_exposure": "none by default",
        "integration_level": "CLASSIC_BACKTEST_REFERENCE",
        "use_now": "Broker/data/strategy separation, analyzers, trade lifecycle",
        "avoid_now": "Migrating to a less active full framework",
        "priority": 4,
        "reason": "经典架构值得借鉴，但当前项目应该保留更小的本地模拟核心。",
    },
    {
        "name": "backtesting.py",
        "repo": "kernc/backtesting.py",
        "asset_focus": "stocks",
        "crypto_exposure": "none",
        "integration_level": "OPTIONAL_ADAPTER",
        "use_now": "Strategy class style, result plotting, simpler backtest ergonomics",
        "avoid_now": "Replacing existing event-driven paper trading",
        "priority": 5,
        "reason": "轻量、适合把现有策略包装成标准接口。",
    },
    {
        "name": "vectorbt",
        "repo": "polakowo/vectorbt",
        "asset_focus": "stocks, ETFs",
        "crypto_exposure": "optional",
        "integration_level": "OPTIONAL_RESEARCH",
        "use_now": "Fast parameter sweeps and signal matrix research",
        "avoid_now": "Live trading and broker logic",
        "priority": 6,
        "reason": "适合批量研究 MA/RSI/趋势参数，但不直接控制交易。",
    },
    {
        "name": "QuantStats",
        "repo": "ranaroussi/quantstats",
        "asset_focus": "performance analytics",
        "crypto_exposure": "none",
        "integration_level": "ALREADY_PARTLY_USED",
        "use_now": "Performance reports, drawdown, Sharpe-style metrics",
        "avoid_now": "Over-optimizing one metric or hiding sample-size weakness",
        "priority": 7,
        "reason": "适合把本地模拟盘报告做得更专业，但不能替代交易风控。",
    },
    {
        "name": "PyPortfolioOpt",
        "repo": "PyPortfolio/PyPortfolioOpt",
        "asset_focus": "long-only portfolio allocation",
        "crypto_exposure": "none",
        "integration_level": "ALREADY_USED",
        "use_now": "Long-only, capped-weight allocation suggestions",
        "avoid_now": "Letting optimizer outputs bypass max-position and cash rules",
        "priority": 8,
        "reason": "已经适合当前项目的组合层建议，继续保持无杠杆长仓约束。",
    },
    {
        "name": "Riskfolio-Lib",
        "repo": "dcajasn/Riskfolio-Lib",
        "asset_focus": "portfolio risk optimization",
        "crypto_exposure": "none",
        "integration_level": "OPTIONAL_RESEARCH_DEPENDENCY",
        "use_now": "Risk parity, CVaR, risk-budgeting ideas",
        "avoid_now": "Making optional dependency required on Windows",
        "priority": 9,
        "reason": "适合增强组合风险预算，但安装复杂度不能影响主流程。",
    },
    {
        "name": "skfolio",
        "repo": "skfolio/skfolio",
        "asset_focus": "portfolio model validation",
        "crypto_exposure": "none",
        "integration_level": "FUTURE_RESEARCH",
        "use_now": "Cross-validation and robustness checks for allocation models",
        "avoid_now": "Adding complex models before enough paper-trading history exists",
        "priority": 10,
        "reason": "适合未来做组合模型稳定性验证。",
    },
]


class FrameworkIntegrationReporter:
    """输出成熟开源项目的集成路线，避免盲目整包替换。"""

    def __init__(self, output_dir: Path = Path("outputs")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        frame = pd.DataFrame(FRAMEWORK_ROWS).sort_values("priority")
        frame.to_csv(self.output_dir / "framework_integration_plan.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame)
        get_store().append_generic_frame("framework_integration_plan", "framework_integration_plan.csv", frame)
        return frame

    def _write_report(self, frame: pd.DataFrame) -> None:
        lines = [
            "# Framework Integration Plan",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "Scope: stocks and options research only. Crypto trading integrations are intentionally excluded.",
            "",
            "| priority | name | integration_level | use_now | avoid_now |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in frame.to_dict(orient="records"):
            lines.append(
                f"| {row['priority']} | {row['name']} | {row['integration_level']} | "
                f"{row['use_now']} | {row['avoid_now']} |"
            )
        (self.output_dir / "framework_integration_plan.md").write_text("\n".join(lines), encoding="utf-8")
