from __future__ import annotations

from pathlib import Path

import pandas as pd

from .database import get_store


FRAMEWORK_ROWS = [
    {
        "name": "QuantConnect LEAN",
        "repo": "QuantConnect/Lean",
        "asset_focus": "stocks, options, futures, forex",
        "crypto_exposure": "optional",
        "integration_level": "REFERENCE_ARCHITECTURE",
        "use_now": "Order model, portfolio model, security type separation, risk controls",
        "avoid_now": "Full engine migration; real broker integrations",
        "priority": 1,
        "reason": "最适合参考股票/期权统一回测和实盘架构，但体量很大，先借鉴设计。",
    },
    {
        "name": "backtesting.py",
        "repo": "kernc/backtesting.py",
        "asset_focus": "stocks",
        "crypto_exposure": "none",
        "integration_level": "OPTIONAL_ADAPTER",
        "use_now": "Strategy class style, result plotting, simpler backtest ergonomics",
        "avoid_now": "Replacing existing event-driven paper trading",
        "priority": 2,
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
        "priority": 3,
        "reason": "适合批量研究 MA/RSI/趋势参数，但不直接控制交易。",
    },
    {
        "name": "Qlib",
        "repo": "microsoft/qlib",
        "asset_focus": "stocks, factors, ML research",
        "crypto_exposure": "none",
        "integration_level": "RESEARCH_ONLY",
        "use_now": "Factor pipeline, dataset discipline, model evaluation workflow",
        "avoid_now": "Heavy ML dependency stack before data quality improves",
        "priority": 4,
        "reason": "适合未来做因子和机器学习研究，现在先学习流程。",
    },
    {
        "name": "vn.py",
        "repo": "vnpy/vnpy",
        "asset_focus": "stocks, futures, options via gateways",
        "crypto_exposure": "optional gateway",
        "integration_level": "REFERENCE_ARCHITECTURE",
        "use_now": "Event engine, gateway boundaries, UI/logging patterns",
        "avoid_now": "Real gateway trading",
        "priority": 5,
        "reason": "成熟事件驱动框架，适合作为长期架构参考。",
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
