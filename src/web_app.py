from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pandas as pd
from flask import Flask, flash, redirect, render_template_string, url_for

from .allocation_optimizer import PortfolioAllocationOptimizer
from .config import BacktestConfig
from .config import LocalPaperConfig
from .local_paper_trader import LocalPaperTrader
from .optimizer import ParameterOptimizer
from .performance import PerformanceReportBuilder


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "local-paper-web-ui"
    config = LocalPaperConfig()
    output_dir = config.output_dir
    app.jinja_env.globals["table"] = _table

    @app.get("/")
    def index():
        snapshot = _snapshot(output_dir)
        tables = {
            "Positions": _read_csv(output_dir / config.positions_file),
            "Recent Decisions": _read_csv(output_dir / config.decision_log_file).tail(10),
            "Recent Orders": _read_csv(output_dir / config.paper_order_log_file).tail(10),
            "Recent Trades": _read_csv(output_dir / config.paper_trade_log_file).tail(10),
            "Performance Metrics": _read_csv(output_dir / config.local_performance_metrics_file),
            "Portfolio Allocation": _read_csv(output_dir / "portfolio_allocation.csv"),
            "Optimization Top 10": _read_csv(output_dir / "optimization_top10.csv"),
        }
        history = _read_csv(output_dir / config.account_history_file)
        return render_template_string(
            TEMPLATE,
            snapshot=snapshot,
            tables=tables,
            equity_svg=_equity_svg(history),
        )

    @app.post("/run-local")
    def run_local():
        start = perf_counter()
        LocalPaperTrader(config).run_once()
        flash(f"Local paper trading run completed in {perf_counter() - start:.1f}s.", "success")
        return redirect(url_for("index"))

    @app.post("/optimize")
    def optimize():
        start = perf_counter()
        best = ParameterOptimizer().run()
        flash(
            (
                "Optimization completed in "
                f"{perf_counter() - start:.1f}s. Best: {best.params_label}, "
                f"return {best.total_return:.2%}, drawdown {best.max_drawdown:.2%}."
            ),
            "success",
        )
        return redirect(url_for("index"))

    @app.post("/research")
    def research():
        start = perf_counter()
        report_builder = PerformanceReportBuilder(output_dir)
        report_builder.build_from_equity_csv(
            config.account_history_file,
            config.local_performance_report_file,
            config.local_performance_metrics_file,
            "Local Paper Trading Performance Report",
        )
        allocation = PortfolioAllocationOptimizer(BacktestConfig(), output_dir=output_dir, target_equity=config.initial_cash).run()
        flash(
            (
                "Research outputs completed in "
                f"{perf_counter() - start:.1f}s. Allocation: {allocation.method}, "
                f"stock {allocation.stock_weight:.2%}, cash {allocation.cash_weight:.2%}."
            ),
            "success",
        )
        return redirect(url_for("index"))

    return app


def _snapshot(output_dir: Path) -> dict[str, str]:
    account = _read_csv(output_dir / "virtual_account.csv")
    report = _read_csv(output_dir / "local_paper_report.csv")
    account_row = account.iloc[-1] if not account.empty else {}
    report_row = report.iloc[-1] if not report.empty else {}
    return {
        "Equity": _money(_get(account_row, "equity", 0.0)),
        "Virtual Cash": _money(_get(account_row, "virtual_cash", 0.0)),
        "Total Return": _pct(_get(report_row, "total_return", 0.0)),
        "Max Drawdown": _pct(_get(report_row, "max_drawdown", 0.0)),
        "Sharpe": f"{float(_get(report_row, 'sharpe_ratio', 0.0)):.2f}",
        "Open Positions": str(int(float(_get(report_row, "open_positions", 0)))),
    }


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<div class="empty">No data yet.</div>'
    frame = frame.copy()
    if len(frame) > 10:
        frame = frame.tail(10)
    return frame.to_html(index=False, classes="data-table", border=0, escape=True)


def _equity_svg(history: pd.DataFrame) -> str:
    if history.empty or "equity" not in history.columns:
        return '<div class="empty">No equity history yet.</div>'
    values = history["equity"].astype(float).tolist()
    if len(values) == 1:
        values = values * 2
    width, height, pad = 900, 220, 14
    low, high = min(values), max(values)
    span = high - low or 1
    points = []
    for index, value in enumerate(values):
        x = pad + index * ((width - 2 * pad) / max(len(values) - 1, 1))
        y = height - pad - ((value - low) / span) * (height - 2 * pad)
        points.append(f"{x:.2f},{y:.2f}")
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Equity curve">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#0f766e" '
        f'stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#d6dbe6"/>'
        f"</svg>"
    )


def _get(row, key: str, default):
    try:
        value = row[key]
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default


def _money(value) -> str:
    return f"${float(value):,.2f}"


def _pct(value) -> str:
    return f"{float(value):.2%}"


TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>US Paper Backtester</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --border: #dfe4ee;
      --accent: #0f766e;
      --accent-dark: #115e59;
      --warning: #b54708;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      font-size: 14px;
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
    }
    .topbar {
      max-width: 1320px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      letter-spacing: 0;
    }
    .subtitle {
      color: var(--muted);
      margin-top: 4px;
      font-size: 13px;
    }
    main {
      max-width: 1320px;
      margin: 0 auto;
      padding: 20px 24px 32px;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    button, .link-button {
      border: 1px solid var(--accent);
      background: var(--accent);
      color: white;
      height: 36px;
      padding: 0 14px;
      border-radius: 6px;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
    }
    button:hover, .link-button:hover { background: var(--accent-dark); }
    .ghost {
      background: white;
      color: var(--accent);
    }
    .ghost:hover {
      background: #eef8f6;
      color: var(--accent-dark);
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(6, minmax(130px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .metric, section, .notice {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .metric {
      padding: 14px;
      min-height: 82px;
    }
    .metric-label {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }
    .metric-value {
      font-size: 22px;
      font-weight: 700;
    }
    .notice {
      padding: 10px 12px;
      margin-bottom: 16px;
      color: var(--accent-dark);
      background: #ecfdf3;
    }
    .layout {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    section {
      padding: 14px;
      overflow: auto;
    }
    section.wide {
      grid-column: 1 / -1;
    }
    h2 {
      margin: 0 0 12px;
      font-size: 16px;
    }
    .chart {
      width: 100%;
      height: 240px;
      border: 1px solid var(--border);
      background: #fbfcff;
      border-radius: 8px;
      padding: 8px;
    }
    .chart svg {
      width: 100%;
      height: 100%;
    }
    .data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    .data-table th, .data-table td {
      padding: 8px 6px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      white-space: nowrap;
    }
    .data-table th {
      color: var(--muted);
      font-weight: 700;
    }
    .empty {
      color: var(--muted);
      padding: 8px 0;
    }
    .ibkr-note {
      color: var(--warning);
      font-size: 12px;
      margin-top: 8px;
    }
    @media (max-width: 1000px) {
      .metrics { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
      .layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>US Paper Backtester</h1>
        <div class="subtitle">Local paper trading dashboard. No broker connection is used by this web app.</div>
      </div>
      <div class="actions">
        <form method="post" action="{{ url_for('run_local') }}"><button type="submit">Run Local Paper</button></form>
        <form method="post" action="{{ url_for('research') }}"><button type="submit" class="ghost">Run Research</button></form>
        <form method="post" action="{{ url_for('optimize') }}"><button type="submit" class="ghost">Run Optimizer</button></form>
        <a class="link-button ghost" href="{{ url_for('index') }}">Refresh</a>
      </div>
    </div>
  </header>
  <main>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="notice">{{ message }}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <div class="metrics">
      {% for label, value in snapshot.items() %}
        <div class="metric">
          <div class="metric-label">{{ label }}</div>
          <div class="metric-value">{{ value }}</div>
        </div>
      {% endfor %}
    </div>

    <div class="layout">
      <section class="wide">
        <h2>Equity Curve</h2>
        <div class="chart">{{ equity_svg|safe }}</div>
      </section>
      {% for title, frame in tables.items() %}
        <section>
          <h2>{{ title }}</h2>
          {{ table(frame)|safe }}
        </section>
      {% endfor %}
      <section class="wide">
        <h2>Safety</h2>
        <div class="ibkr-note">This web app only runs the local simulation. It does not connect to IBKR and does not place real or broker-side paper orders.</div>
      </section>
    </div>
  </main>
</body>
</html>
"""
