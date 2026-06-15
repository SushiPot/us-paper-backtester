from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class DashboardSnapshot:
    equity: float
    virtual_cash: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    open_positions: int


class DashboardBuilder:
    """Build a static local dashboard from paper-trading CSV files."""

    def __init__(self, output_dir: Path = Path("outputs")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build(self) -> Path:
        snapshot = self._load_snapshot()
        positions = self._read_csv("positions.csv")
        orders = self._read_csv("paper_order_log.csv").tail(10)
        trades = self._read_csv("paper_trade_log.csv").tail(10)
        decisions = self._read_csv("decision_log.csv").tail(10)
        performance = self._read_csv("local_performance_metrics.csv")
        allocation = self._read_csv("portfolio_allocation.csv")
        history = self._read_csv("account_history.csv")

        output_path = self.output_dir / "dashboard.html"
        output_path.write_text(
            self._render(snapshot, positions, orders, trades, decisions, performance, allocation, history),
            encoding="utf-8",
        )
        return output_path

    def _load_snapshot(self) -> DashboardSnapshot:
        account = self._read_csv("virtual_account.csv")
        report = self._read_csv("local_paper_report.csv")

        account_row = account.iloc[-1] if not account.empty else {}
        report_row = report.iloc[-1] if not report.empty else {}

        return DashboardSnapshot(
            equity=float(_get(account_row, "equity", 0.0)),
            virtual_cash=float(_get(account_row, "virtual_cash", 0.0)),
            total_return=float(_get(report_row, "total_return", 0.0)),
            max_drawdown=float(_get(report_row, "max_drawdown", 0.0)),
            sharpe_ratio=float(_get(report_row, "sharpe_ratio", 0.0)),
            open_positions=int(float(_get(report_row, "open_positions", 0))),
        )

    def _read_csv(self, filename: str) -> pd.DataFrame:
        path = self.output_dir / filename
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    def _render(
        self,
        snapshot: DashboardSnapshot,
        positions: pd.DataFrame,
        orders: pd.DataFrame,
        trades: pd.DataFrame,
        decisions: pd.DataFrame,
        performance: pd.DataFrame,
        allocation: pd.DataFrame,
        history: pd.DataFrame,
    ) -> str:
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>US Paper Backtester Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #677084;
      --border: #dfe4ee;
      --accent: #0f766e;
      --danger: #b42318;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      padding: 18px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--border);
    }}
    h1 {{
      margin: 0;
      font-size: 22px;
      letter-spacing: 0;
    }}
    main {{
      padding: 20px 24px 32px;
      max-width: 1280px;
      margin: 0 auto;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(6, minmax(140px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    .metric {{ padding: 14px; min-height: 82px; }}
    .label {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .value {{ font-size: 22px; font-weight: 700; }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    section {{ padding: 14px; overflow: hidden; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 8px 6px;
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }}
    th {{ color: var(--muted); font-weight: 700; }}
    .chart {{
      width: 100%;
      height: 220px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fbfcff;
      padding: 8px;
    }}
    .empty {{ color: var(--muted); font-size: 13px; padding: 8px 0; }}
    .positive {{ color: var(--accent); }}
    .negative {{ color: var(--danger); }}
    @media (max-width: 980px) {{
      .metrics {{ grid-template-columns: repeat(2, minmax(140px, 1fr)); }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>US Paper Backtester Dashboard</h1>
  </header>
  <main>
    <div class="metrics">
      {self._metric("Equity", _money(snapshot.equity))}
      {self._metric("Cash", _money(snapshot.virtual_cash))}
      {self._metric("Total Return", _pct(snapshot.total_return), snapshot.total_return)}
      {self._metric("Max Drawdown", _pct(snapshot.max_drawdown), snapshot.max_drawdown)}
      {self._metric("Sharpe", f"{snapshot.sharpe_ratio:.2f}")}
      {self._metric("Open Positions", str(snapshot.open_positions))}
    </div>
    <section style="margin-bottom:16px;">
      <h2>Equity Curve</h2>
      <div class="chart">{self._render_svg(history)}</div>
    </section>
    <div class="grid">
      <section><h2>Positions</h2>{self._table(positions)}</section>
      <section><h2>Recent Decisions</h2>{self._table(decisions)}</section>
      <section><h2>Recent Orders</h2>{self._table(orders)}</section>
      <section><h2>Recent Trades</h2>{self._table(trades)}</section>
      <section><h2>Performance Metrics</h2>{self._table(performance)}</section>
      <section><h2>Portfolio Allocation</h2>{self._table(allocation)}</section>
    </div>
  </main>
</body>
</html>"""

    @staticmethod
    def _metric(label: str, value: str, numeric: float | None = None) -> str:
        cls = ""
        if numeric is not None:
            cls = " positive" if numeric >= 0 else " negative"
        return f'<div class="metric"><div class="label">{html.escape(label)}</div><div class="value{cls}">{html.escape(value)}</div></div>'

    @staticmethod
    def _table(frame: pd.DataFrame) -> str:
        if frame.empty:
            return '<div class="empty">No data yet.</div>'
        frame = frame.copy()
        if len(frame) > 10:
            frame = frame.tail(10)
        headers = "".join(f"<th>{html.escape(str(column))}</th>" for column in frame.columns)
        rows = []
        for _, row in frame.iterrows():
            cells = "".join(f"<td>{html.escape(_format_cell(value))}</td>" for value in row.tolist())
            rows.append(f"<tr>{cells}</tr>")
        return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"

    @staticmethod
    def _render_svg(history: pd.DataFrame) -> str:
        if history.empty or "equity" not in history.columns:
            return '<div class="empty">No equity history yet.</div>'
        values = history["equity"].astype(float).tolist()
        if len(values) == 1:
            values = values * 2
        width, height, pad = 900, 200, 12
        low, high = min(values), max(values)
        span = high - low or 1
        points = []
        for index, value in enumerate(values):
            x = pad + index * ((width - 2 * pad) / max(len(values) - 1, 1))
            y = height - pad - ((value - low) / span) * (height - 2 * pad)
            points.append(f"{x:.2f},{y:.2f}")
        return (
            f'<svg viewBox="0 0 {width} {height}" width="100%" height="100%" role="img" '
            f'aria-label="Equity curve"><polyline points="{" ".join(points)}" fill="none" '
            f'stroke="#0f766e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        )


def _get(row, key: str, default):
    try:
        value = row[key]
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _pct(value: float) -> str:
    return f"{value:.2%}"


def _format_cell(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
