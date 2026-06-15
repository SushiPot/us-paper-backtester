from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PerformanceSummary:
    """专业绩效报告的核心指标。"""

    total_return: float
    annual_return: float
    annual_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    best_day: float
    worst_day: float
    positive_day_rate: float


class PerformanceReportBuilder:
    """生成 QuantStats 风格绩效报告；依赖不可用时自动降级为本地 HTML。"""

    def __init__(self, output_dir: Path = Path("outputs")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_from_equity_csv(
        self,
        csv_filename: str,
        html_filename: str,
        metrics_filename: str,
        title: str,
        equity_column: str = "equity",
    ) -> PerformanceSummary | None:
        path = self.output_dir / csv_filename
        if not path.exists() or path.stat().st_size == 0:
            return None

        frame = pd.read_csv(path)
        if frame.empty or equity_column not in frame.columns:
            return None

        equity = self._extract_equity_series(frame, equity_column)
        return self.build_from_series(equity, html_filename, metrics_filename, title)

    def build_from_series(
        self,
        equity_curve: pd.Series,
        html_filename: str,
        metrics_filename: str,
        title: str,
    ) -> PerformanceSummary | None:
        equity = equity_curve.dropna().astype(float)
        equity = equity[equity > 0]
        if len(equity) < 2:
            return None

        equity = equity.groupby(equity.index).last().sort_index()
        returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        if returns.empty:
            return None

        summary = self._calculate_summary(equity, returns)
        self._write_metrics(summary, metrics_filename)

        if not self._write_quantstats_report(returns, html_filename, title):
            self._write_fallback_html(equity, returns, summary, html_filename, title)
        return summary

    @staticmethod
    def _extract_equity_series(frame: pd.DataFrame, equity_column: str) -> pd.Series:
        date_column = "market_date" if "market_date" in frame.columns else "time" if "time" in frame.columns else None
        if date_column:
            index = pd.to_datetime(frame[date_column], errors="coerce")
        else:
            index = pd.RangeIndex(len(frame))

        equity = pd.Series(frame[equity_column].astype(float).to_numpy(), index=index, name="equity")
        equity = equity[~pd.isna(equity.index)]
        return equity

    @staticmethod
    def _calculate_summary(equity: pd.Series, returns: pd.Series) -> PerformanceSummary:
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
        days = max((pd.Timestamp(equity.index[-1]) - pd.Timestamp(equity.index[0])).days, 1)
        annual_return = float((1 + total_return) ** (365 / days) - 1)
        annual_volatility = float(returns.std(ddof=0) * np.sqrt(252)) if returns.std(ddof=0) > 0 else 0.0
        sharpe = float(returns.mean() / returns.std(ddof=0) * np.sqrt(252)) if returns.std(ddof=0) > 0 else 0.0

        downside = returns[returns < 0]
        sortino = float(returns.mean() / downside.std(ddof=0) * np.sqrt(252)) if downside.std(ddof=0) > 0 else 0.0
        drawdown = equity / equity.cummax() - 1
        max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
        calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
        return PerformanceSummary(
            total_return=total_return,
            annual_return=annual_return,
            annual_volatility=annual_volatility,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_drawdown,
            calmar_ratio=calmar,
            best_day=float(returns.max()),
            worst_day=float(returns.min()),
            positive_day_rate=float((returns > 0).mean()),
        )

    def _write_metrics(self, summary: PerformanceSummary, filename: str) -> None:
        pd.DataFrame([summary.__dict__]).to_csv(self.output_dir / filename, index=False, encoding="utf-8-sig")

    def _write_quantstats_report(self, returns: pd.Series, filename: str, title: str) -> bool:
        if len(returns) < 5 or int((returns != 0).sum()) < 2:
            return False
        try:
            import quantstats as qs

            output_path = self.output_dir / filename
            qs.reports.html(returns, output=str(output_path), title=title)
            return True
        except Exception as exc:
            print(f"[WARN] QuantStats 报告生成失败，使用本地 HTML 降级报告: {type(exc).__name__}: {exc}", flush=True)
            return False

    def _write_fallback_html(
        self,
        equity: pd.Series,
        returns: pd.Series,
        summary: PerformanceSummary,
        filename: str,
        title: str,
    ) -> None:
        rows = "".join(
            f"<tr><td>{html.escape(label)}</td><td>{value}</td></tr>"
            for label, value in [
                ("Total Return", _pct(summary.total_return)),
                ("Annual Return", _pct(summary.annual_return)),
                ("Annual Volatility", _pct(summary.annual_volatility)),
                ("Sharpe Ratio", f"{summary.sharpe_ratio:.2f}"),
                ("Sortino Ratio", f"{summary.sortino_ratio:.2f}"),
                ("Max Drawdown", _pct(summary.max_drawdown)),
                ("Calmar Ratio", f"{summary.calmar_ratio:.2f}"),
                ("Best Day", _pct(summary.best_day)),
                ("Worst Day", _pct(summary.worst_day)),
                ("Positive Day Rate", _pct(summary.positive_day_rate)),
            ]
        )
        html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 24px; color: #172033; }}
    table {{ border-collapse: collapse; min-width: 420px; }}
    td {{ border-bottom: 1px solid #dfe4ee; padding: 9px 12px; }}
    td:first-child {{ color: #667085; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p>Fallback report generated locally because QuantStats was unavailable or failed.</p>
  <table>{rows}</table>
  <p>Equity points: {len(equity)} | Return points: {len(returns)}</p>
</body>
</html>"""
        (self.output_dir / filename).write_text(html_text, encoding="utf-8")


def _pct(value: float) -> str:
    return f"{value:.2%}"
