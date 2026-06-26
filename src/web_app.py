from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pandas as pd
from flask import Flask, flash, redirect, render_template_string, url_for

from .agents.manager import ManagerRunConfig, OverallManager
from .allocation_optimizer import PortfolioAllocationOptimizer
from .backtester import Backtester
from .config import BacktestConfig
from .config import LocalPaperConfig
from .dashboard import SystemStatusBuilder
from .database import DEFAULT_DB_PATH
from .fundamental_data import FundamentalDataAnalyzer
from .local_paper_trader import LocalPaperTrader
from .macro_data import MacroDataAnalyzer
from .optimizer import ParameterOptimizer
from .performance import PerformanceReportBuilder
from .strategy_health import StrategyHealthAnalyzer
from .strategy_variant_evaluator import StrategyVariantEvaluator
from .self_optimizer import SelfOptimizationReporter
from .walk_forward import WalkForwardValidator


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
            "System Status": SystemStatusBuilder(output_dir).build(),
            "Positions": _read_csv(output_dir / config.positions_file),
            "Recent Decisions": _read_csv(output_dir / config.decision_log_file).tail(10),
            "Recent Orders": _read_csv(output_dir / config.paper_order_log_file).tail(10),
            "Recent Trades": _read_csv(output_dir / config.paper_trade_log_file).tail(10),
            "Performance Metrics": _read_csv(output_dir / config.local_performance_metrics_file),
            "Data Health Summary": _read_csv(output_dir / "data_health_summary.csv"),
            "Data Health Detail": _read_csv(output_dir / "data_health.csv"),
            "Market Environment Summary": _read_csv(output_dir / "market_environment_summary.csv"),
            "Market Environment Detail": _read_csv(output_dir / "market_environment.csv"),
            "Macro Environment Summary": _read_csv(output_dir / "macro_environment_summary.csv"),
            "Macro Indicators": _read_csv(output_dir / "macro_indicators.csv"),
            "Signal Evaluation Summary": _read_csv(output_dir / "signal_evaluation_summary.csv"),
            "Signal Evaluation Detail": _read_csv(output_dir / "signal_evaluation.csv"),
            "Relative Strength Rank": _read_csv(output_dir / "relative_strength_rank.csv"),
            "Fundamental Summary": _read_csv(output_dir / "fundamental_summary.csv"),
            "Fundamental Snapshot": _read_csv(output_dir / "fundamental_snapshot.csv"),
            "Strategy Scorecard": _read_csv(output_dir / "strategy_scorecard.csv"),
            "Backtest Strategy Scorecard": _read_csv(output_dir / "backtest_strategy_scorecard.csv"),
            "Strategy Health": _read_csv(output_dir / "strategy_health.csv"),
            "Market Regime": _read_csv(output_dir / "market_regime.csv"),
            "Walk Forward Summary": _read_csv(output_dir / "walk_forward_summary.csv"),
            "Walk Forward Results": _read_csv(output_dir / "walk_forward_results.csv"),
            "Strategy Variant Scores": _read_csv(output_dir / "strategy_variant_scores.csv"),
            "Adaptive Strategy Profile": _read_csv(output_dir / "adaptive_strategy_profile.csv"),
            "Self Optimization Actions": _read_csv(output_dir / "self_optimization_actions.csv"),
            "GitHub Project Candidates": _read_csv(output_dir / "github_project_candidates.csv"),
            "Framework Integration Plan": _read_csv(output_dir / "framework_integration_plan.csv"),
            "Options Research Summary": _read_csv(output_dir / "options_research_summary.csv"),
            "Options Liquidity Watchlist": _read_csv(output_dir / "options_liquidity_watchlist.csv"),
            "Online Portfolio Summary": _read_csv(output_dir / "online_portfolio_allocation_summary.csv"),
            "Online Portfolio Allocation": _read_csv(output_dir / "online_portfolio_allocation.csv"),
            "Portfolio Allocation": _read_csv(output_dir / "portfolio_allocation.csv"),
            "Agent Run Log": _read_csv(output_dir / "agent_run_log.csv").tail(10),
            "Manager Modes": _manager_modes_table(),
            "Online Research Projects": _read_csv(output_dir / "online_research_projects.csv"),
            "LLM Manager Review": _file_status(output_dir / "llm_manager_review.md"),
            "Optimization Top 10": _read_csv(output_dir / "optimization_top10.csv"),
            "Trained Backtest Report": _read_csv(output_dir / "trained" / "backtest_report.csv"),
            "Database Status": _database_status(),
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

    @app.post("/trained-backtest")
    def trained_backtest():
        start = perf_counter()
        report = Backtester(
            BacktestConfig(
                fast_ma=30,
                slow_ma=60,
                rsi_period=14,
                rsi_limit=60.0,
                stop_loss_pct=-0.05,
                take_profit_pct=0.30,
                max_holding_days=30,
                output_dir=output_dir / "trained",
            )
        ).run()
        flash(
            (
                "Trained backtest completed in "
                f"{perf_counter() - start:.1f}s. Return {report.total_return:.2%}, "
                f"drawdown {report.max_drawdown:.2%}, Sharpe {report.sharpe_ratio:.2f}."
            ),
            "success",
        )
        return redirect(url_for("index"))

    @app.post("/walk-forward")
    def walk_forward():
        start = perf_counter()
        summary = WalkForwardValidator(BacktestConfig(), output_dir=output_dir).run()
        health = StrategyHealthAnalyzer(config, BacktestConfig()).run()
        flash(
            (
                "Walk-forward completed in "
                f"{perf_counter() - start:.1f}s. Stability {summary.stability_score:.1f}, "
                f"action {summary.recommended_action}. Health {health.overall_score:.1f}."
            ),
            "success",
        )
        return redirect(url_for("index"))

    @app.post("/self-optimize")
    def self_optimize():
        start = perf_counter()
        variants = StrategyVariantEvaluator(BacktestConfig(), output_dir=output_dir).run()
        actions = SelfOptimizationReporter(output_dir).run()
        best_variant = str(variants.iloc[0]["variant"]) if not variants.empty else "none"
        flash(
            (
                "Self optimization completed in "
                f"{perf_counter() - start:.1f}s. Best variant {best_variant}. "
                f"Actions {len(actions)}."
            ),
            "success",
        )
        return redirect(url_for("index"))

    @app.post("/manager")
    def manager():
        start = perf_counter()
        results = OverallManager(ManagerRunConfig.for_mode("local")).run_once()
        flash(f"Overall Manager completed in {perf_counter() - start:.1f}s with {len(results)} agent results.", "success")
        return redirect(url_for("index"))

    @app.post("/manager-online")
    def manager_online():
        start = perf_counter()
        results = OverallManager(ManagerRunConfig.for_mode("online")).run_once()
        flash(f"Online Manager completed in {perf_counter() - start:.1f}s with {len(results)} agent results.", "success")
        return redirect(url_for("index"))

    @app.post("/manager-ai")
    def manager_ai():
        start = perf_counter()
        results = OverallManager(ManagerRunConfig.for_mode("ai")).run_once()
        flash(f"AI Manager completed in {perf_counter() - start:.1f}s with {len(results)} agent results.", "success")
        return redirect(url_for("index"))

    @app.post("/online-data")
    def online_data():
        start = perf_counter()
        macro = MacroDataAnalyzer(output_dir=output_dir).run()
        fundamentals = FundamentalDataAnalyzer(output_dir=output_dir).run()
        macro_status = str(macro.iloc[-1].get("macro_status", "NO_DATA")) if not macro.empty else "NO_DATA"
        fundamental_status = str(fundamentals.iloc[-1].get("status", "NO_DATA")) if not fundamentals.empty else "NO_DATA"
        flash(
            (
                "Online data refreshed in "
                f"{perf_counter() - start:.1f}s. Macro {macro_status}, fundamentals {fundamental_status}."
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
        walk_forward = WalkForwardValidator(BacktestConfig(), output_dir=output_dir).run()
        health = StrategyHealthAnalyzer(config, BacktestConfig()).run()
        flash(
            (
                "Research outputs completed in "
                f"{perf_counter() - start:.1f}s. Allocation: {allocation.method}, "
                f"stock {allocation.stock_weight:.2%}, cash {allocation.cash_weight:.2%}. "
                f"Walk-forward {walk_forward.stability_score:.1f}. "
                f"Health {health.overall_score:.1f} ({health.health_status})."
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
        "Health Score": _health_score(output_dir),
        "Strategy Leader": _strategy_leader(output_dir),
        "Data Health": _data_health_status(output_dir),
        "Market Env": _market_environment_status(output_dir),
        "Daemon": _daemon_status(output_dir),
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


def _file_status(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(
            [
                {
                    "file": path.name,
                    "status": "missing",
                    "bytes": 0,
                    "hint": "Run AI Manager after setting OPENROUTER_API_KEY.",
                }
            ]
        )
    return pd.DataFrame(
        [
            {
                "file": path.name,
                "status": "ready",
                "bytes": path.stat().st_size,
                "hint": "Open outputs/llm_manager_review.md to read the AI review.",
            }
        ]
    )


def _manager_modes_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "mode": "local",
                "network": "off",
                "llm": "off",
                "agents": "MarketData, LocalPaper, Research, Risk, Report",
            },
            {
                "mode": "online",
                "network": "on",
                "llm": "off",
                "agents": "Local mode + OnlineResearch",
            },
            {
                "mode": "ai",
                "network": "on",
                "llm": "on",
                "agents": "Online mode + LLMReviewer",
            },
        ]
    )


def _database_status() -> pd.DataFrame:
    if not DEFAULT_DB_PATH.exists():
        return pd.DataFrame([{"database": str(DEFAULT_DB_PATH), "status": "missing", "table": "", "rows": 0}])

    import sqlite3

    tables = [
        "accounts",
        "account_history",
        "positions",
        "orders",
        "trades",
        "decisions",
        "run_logs",
        "agent_runs",
        "notifications",
        "daemon_runs",
        "backtest_reports",
        "portfolio_allocations",
        "generic_frames",
    ]
    rows = []
    with sqlite3.connect(DEFAULT_DB_PATH) as connection:
        for table in tables:
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            rows.append({"database": str(DEFAULT_DB_PATH), "status": "ready", "table": table, "rows": count})
    return pd.DataFrame(rows)


def _health_score(output_dir: Path) -> str:
    health = _read_csv(output_dir / "strategy_health.csv")
    if health.empty:
        return "N/A"
    row = health.iloc[-1]
    score = float(_get(row, "overall_score", 0.0))
    status = _get(row, "health_status", "")
    return f"{score:.1f} {status}"


def _strategy_leader(output_dir: Path) -> str:
    scorecard = _read_csv(output_dir / "strategy_scorecard.csv")
    if scorecard.empty:
        return "N/A"
    row = scorecard.iloc[0]
    score = float(_get(row, "strategy_score", 0.0))
    return f"{_get(row, 'strategy_name', '')} {score:.1f}"


def _data_health_status(output_dir: Path) -> str:
    frame = _read_csv(output_dir / "data_health_summary.csv")
    if frame.empty:
        return "N/A"
    row = frame.iloc[-1]
    return f"{_get(row, 'status', '')} lag={int(float(_get(row, 'max_lag_calendar_days', 0)))}d"


def _market_environment_status(output_dir: Path) -> str:
    frame = _read_csv(output_dir / "market_environment_summary.csv")
    if frame.empty:
        return "N/A"
    row = frame.iloc[-1]
    return f"{_get(row, 'market_status', '')}"


def _daemon_status(output_dir: Path) -> str:
    path = output_dir / "agent_status.json"
    if not path.exists() or path.stat().st_size == 0:
        return "N/A"
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("status", ""))
    except Exception:
        return "ERROR"


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
        <form method="post" action="{{ url_for('manager') }}"><button type="submit" class="ghost">Run Manager</button></form>
        <form method="post" action="{{ url_for('manager_online') }}"><button type="submit" class="ghost">Run Online Manager</button></form>
        <form method="post" action="{{ url_for('manager_ai') }}"><button type="submit" class="ghost">Run AI Manager</button></form>
        <form method="post" action="{{ url_for('online_data') }}"><button type="submit" class="ghost">Refresh Online Data</button></form>
        <form method="post" action="{{ url_for('research') }}"><button type="submit" class="ghost">Run Research</button></form>
        <form method="post" action="{{ url_for('self_optimize') }}"><button type="submit" class="ghost">Run Self Optimize</button></form>
        <form method="post" action="{{ url_for('walk_forward') }}"><button type="submit" class="ghost">Run Walk-Forward</button></form>
        <form method="post" action="{{ url_for('trained_backtest') }}"><button type="submit" class="ghost">Run Trained Backtest</button></form>
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
