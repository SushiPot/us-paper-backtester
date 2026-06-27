from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .database import DEFAULT_DB_PATH


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class DashboardSnapshot:
    equity: float
    virtual_cash: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    open_positions: int


class SystemStatusBuilder:
    """Build compact status-light rows for the dashboard."""

    def __init__(self, output_dir: Path = Path("outputs"), daemon_stale_minutes: int = 45) -> None:
        self.output_dir = output_dir
        self.daemon_stale_minutes = daemon_stale_minutes

    def build(self, persist: bool = True) -> pd.DataFrame:
        rows = [
            self._data_health_row(),
            self._market_environment_row(),
            self._macro_environment_row(),
            self._benchmark_gate_row(),
            self._universe_row(),
            self._signal_evaluation_row(),
            self._relative_strength_row(),
            self._factor_lab_row(),
            self._loss_attribution_row(),
            self._fundamental_row(),
            self._daemon_row(),
            self._local_account_row(),
            self._positions_row(),
            self._database_row(),
        ]
        frame = pd.DataFrame(rows)
        if persist:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            frame.to_csv(self.output_dir / "dashboard_status.csv", index=False)
        return frame

    def _data_health_row(self) -> dict[str, str]:
        path = self.output_dir / "data_health_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Data Health", "GRAY", "MISSING", "No data health summary yet.", "", "Run Local Paper.")

        row = frame.iloc[-1]
        status = str(_get(row, "status", "UNKNOWN"))
        light = "GREEN" if status == "OK" else "YELLOW" if status == "WARN" else "RED"
        detail = (
            f"ok={int(float(_get(row, 'ok_count', 0)))} "
            f"warn={int(float(_get(row, 'warn_count', 0)))} "
            f"missing={int(float(_get(row, 'missing_count', 0)))} "
            f"max_lag={int(float(_get(row, 'max_lag_calendar_days', 0)))}d"
        )
        action = "OK" if light == "GREEN" else "Refresh data and inspect data_health.csv."
        return self._row("Data Health", light, status, detail, _file_updated_at(path), action)

    def _market_environment_row(self) -> dict[str, str]:
        path = self.output_dir / "market_environment_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Market Environment", "GRAY", "MISSING", "No environment summary yet.", "", "Run Local Paper.")

        row = frame.iloc[-1]
        status = str(_get(row, "market_status", "UNKNOWN"))
        action_value = str(_get(row, "recommended_action", ""))
        light = "GREEN" if status == "RISK_ON" else "YELLOW" if status == "NEUTRAL" else "RED"
        detail = f"action={action_value}; reason={_get(row, 'reason', '')}"
        return self._row("Market Environment", light, status, detail, _file_updated_at(path), action_value or "Review market_environment.csv.")

    def _macro_environment_row(self) -> dict[str, str]:
        path = self.output_dir / "macro_environment_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Macro Environment", "GRAY", "MISSING", "No FRED macro summary yet.", "", "Run online_data_main.py.")

        row = frame.iloc[-1]
        status = str(_get(row, "macro_status", "UNKNOWN"))
        action_value = str(_get(row, "recommended_action", ""))
        risk_score = float(_get(row, "risk_score", 0.0))
        light = "GREEN" if status == "RISK_ON" else "YELLOW" if status == "NEUTRAL" else "RED"
        detail = f"risk_score={risk_score:.0f}; action={action_value}; reason={_get(row, 'reason', '')}"
        return self._row("Macro Environment", light, status, detail, _file_updated_at(path), action_value or "Review macro_environment_summary.csv.")

    def _benchmark_gate_row(self) -> dict[str, str]:
        path = self.output_dir / "benchmark_gate_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Benchmark Gate", "GRAY", "MISSING", "No benchmark gate summary yet.", "", "Run Local Paper.")

        row = frame.iloc[-1]
        status = str(_get(row, "status", "UNKNOWN"))
        action_value = str(_get(row, "recommended_action", ""))
        local_return = float(_get(row, "local_return", 0.0))
        benchmark_return = float(_get(row, "benchmark_return", 0.0))
        excess_return = float(_get(row, "excess_return", 0.0))
        if action_value == "ALLOW_NORMAL_SIMULATION":
            light = "GREEN"
        elif action_value == "PAUSE_NEW_BUYS":
            light = "RED"
        else:
            light = "YELLOW"
        detail = (
            f"local={local_return:.2%}; benchmark={benchmark_return:.2%}; "
            f"excess={excess_return:.2%}; action={action_value}"
        )
        return self._row("Benchmark Gate", light, status, detail, _file_updated_at(path), action_value or "Review benchmark_gate_summary.csv.")

    def _universe_row(self) -> dict[str, str]:
        path = self.output_dir / "universe_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Universe", "GRAY", "MISSING", "No universe filter summary yet.", "", "Run Local Paper or Factor Lab.")

        row = frame.iloc[-1]
        status = str(_get(row, "status", "UNKNOWN"))
        passed = int(float(_get(row, "tradable_passed", 0)))
        total = int(float(_get(row, "total_symbols", 0)))
        rejected = int(float(_get(row, "rejected", 0)))
        light = "GREEN" if status == "OK" else "YELLOW" if status == "WARN" else "RED"
        detail = f"tradable={passed}/{total}; rejected={rejected}"
        action = "OK" if light == "GREEN" else "Refresh data or inspect universe_filter.csv."
        return self._row("Universe", light, status, detail, _file_updated_at(path), action)

    def _signal_evaluation_row(self) -> dict[str, str]:
        path = self.output_dir / "signal_evaluation_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Signal Evaluation", "GRAY", "MISSING", "No precision/recall summary yet.", "", "Run Local Paper.")

        if "signal_count" in frame.columns:
            eligible = frame[pd.to_numeric(frame["signal_count"], errors="coerce").fillna(0) >= 100].copy()
        else:
            eligible = frame.copy()
        if eligible.empty:
            eligible = frame.copy()
        sort_columns = [column for column in ["edge_vs_all_future_return", "precision", "f1"] if column in eligible.columns]
        row = eligible.sort_values(sort_columns, ascending=[False] * len(sort_columns)).iloc[0] if sort_columns else eligible.iloc[0]
        precision = float(_get(row, "precision", 0.0))
        recall = float(_get(row, "recall", 0.0))
        f1 = float(_get(row, "f1", 0.0))
        edge = float(_get(row, "edge_vs_all_future_return", 0.0))
        light = "GREEN" if precision >= 0.50 and edge > 0 else "YELLOW" if precision >= 0.40 and edge > 0 else "RED"
        detail = (
            f"{_get(row, 'strategy_name', '')} h={int(float(_get(row, 'horizon_days', 0)))}d; "
            f"precision={precision:.1%}; recall={recall:.1%}; f1={f1:.1%}; "
            f"edge={edge:.1%}; signals={int(float(_get(row, 'signal_count', 0)))}"
        )
        return self._row("Signal Evaluation", light, "READY", detail, _file_updated_at(path), "Prefer positive edge, then precision.")

    def _relative_strength_row(self) -> dict[str, str]:
        path = self.output_dir / "relative_strength_rank.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Relative Strength", "GRAY", "MISSING", "No ranking yet.", "", "Run Local Paper.")

        row = frame.sort_values("rank").iloc[0]
        score = float(_get(row, "relative_strength_score", 0.0))
        status = str(_get(row, "status", "WATCH"))
        light = "GREEN" if status == "PASS" else "YELLOW"
        detail = f"leader={_get(row, 'symbol', '')}; score={score:.1f}; {_get(row, 'reason', '')}"
        return self._row("Relative Strength", light, status, detail, _file_updated_at(path), "Buy candidates should rank near the top.")

    def _factor_lab_row(self) -> dict[str, str]:
        path = self.output_dir / "factor_lab_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Factor Lab", "GRAY", "MISSING", "No factor research summary yet.", "", "Run Factor Lab or Local Paper.")

        row = frame.iloc[0]
        status = str(_get(row, "status", "UNKNOWN"))
        score = float(_get(row, "factor_score", 0.0))
        rank_ic = float(_get(row, "rank_ic_mean", 0.0))
        spread = float(_get(row, "long_short_avg_return", 0.0))
        if status == "LEADING":
            light = "GREEN"
        elif status in {"OBSERVE", "NEEDS_MORE_DATA"}:
            light = "YELLOW"
        else:
            light = "RED"
        detail = (
            f"leader={_get(row, 'factor_name', '')}; score={score:.1f}; "
            f"rank_ic={rank_ic:.3f}; spread={spread:.2%}"
        )
        return self._row("Factor Lab", light, status, detail, _file_updated_at(path), "Prefer factors with positive Rank IC and long-short spread.")

    def _loss_attribution_row(self) -> dict[str, str]:
        path = self.output_dir / "loss_attribution_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Loss Attribution", "GRAY", "MISSING", "No loss attribution yet.", "", "Run Local Paper.")

        row = frame.iloc[-1]
        total_return = float(_get(row, "total_return", 0.0))
        total_pnl = float(_get(row, "total_pnl", 0.0))
        open_pnl = float(_get(row, "open_unrealized_pnl", 0.0))
        largest_loss_symbol = str(_get(row, "largest_loss_symbol", ""))
        light = "GREEN" if total_pnl >= 0 else "YELLOW" if total_return > -0.02 else "RED"
        status = "PROFITABLE" if total_pnl >= 0 else "LOSING"
        detail = (
            f"total_pnl={_money(total_pnl)}; open_pnl={_money(open_pnl)}; "
            f"largest_loss={largest_loss_symbol or 'none'}"
        )
        action = "OK" if total_pnl >= 0 else "Inspect loss_attribution_report.md before adding risk."
        return self._row("Loss Attribution", light, status, detail, _file_updated_at(path), action)

    def _fundamental_row(self) -> dict[str, str]:
        path = self.output_dir / "fundamental_summary.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Fundamentals", "GRAY", "MISSING", "No SEC fundamental summary yet.", "", "Run online_data_main.py.")

        row = frame.iloc[-1]
        status = str(_get(row, "status", "UNKNOWN"))
        light = "GREEN" if status == "OK" else "YELLOW" if status == "WARN" else "RED"
        detail = (
            f"symbols={int(float(_get(row, 'symbols', 0)))}; "
            f"metrics_ok={int(float(_get(row, 'metrics_ok', 0)))}; "
            f"missing={int(float(_get(row, 'metrics_missing', 0)))}"
        )
        action = "OK" if light == "GREEN" else "Inspect fundamental_snapshot.csv."
        return self._row("Fundamentals", light, status, detail, _file_updated_at(path), action)

    def _daemon_row(self) -> dict[str, str]:
        path = self.output_dir / "agent_status.json"
        if not path.exists() or path.stat().st_size == 0:
            return self._row("Daemon", "GRAY", "MISSING", "No daemon status file yet.", "", "Start run_daemon.cmd if you want 24-hour monitoring.")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return self._row("Daemon", "RED", "ERROR", f"Bad status JSON: {type(exc).__name__}: {exc}", _file_updated_at(path), "Inspect outputs/agent_status.json.")

        status = str(data.get("status", "UNKNOWN"))
        updated_text = str(data.get("local_time") or data.get("updated_at") or "")
        stale = self._is_stale(updated_text)
        light = "YELLOW" if stale else "GREEN" if status in {"IDLE", "RUNNING"} else "RED"
        detail = str(data.get("message", ""))
        action = "Keep daemon running." if not stale else "Daemon status is stale; restart run_daemon.cmd."
        display_status = "STALE" if stale else status
        return self._row("Daemon", light, display_status, detail, updated_text, action)

    def _local_account_row(self) -> dict[str, str]:
        path = self.output_dir / "virtual_account.csv"
        frame = _read_csv_path(path)
        if frame.empty:
            return self._row("Local Paper Account", "GRAY", "MISSING", "No virtual account yet.", "", "Run local_paper_main.py --once.")

        row = frame.iloc[-1]
        equity = float(_get(row, "equity", 0.0))
        cash = float(_get(row, "virtual_cash", 0.0))
        account_day = str(_get(row, "as_of_date", ""))
        detail = f"as_of={account_day}; equity={_money(equity)}; cash={_money(cash)}"
        light = "GREEN" if equity > 0 else "RED"
        return self._row("Local Paper Account", light, "READY", detail, _file_updated_at(path), "OK")

    def _positions_row(self) -> dict[str, str]:
        path = self.output_dir / "positions.csv"
        frame = _read_csv_path(path)
        count = 0 if frame.empty else len(frame)
        light = "GREEN" if count <= 5 else "RED"
        status = "OK" if count <= 5 else "TOO_MANY"
        detail = f"open_positions={count}; limit=5"
        action = "OK" if count <= 5 else "Reduce positions in simulation before adding new buys."
        return self._row("Positions", light, status, detail, _file_updated_at(path), action)

    def _database_row(self) -> dict[str, str]:
        if not DEFAULT_DB_PATH.exists():
            return self._row("SQLite Database", "GRAY", "MISSING", str(DEFAULT_DB_PATH), "", "Run any manager/local paper task to create the database.")
        size_kb = DEFAULT_DB_PATH.stat().st_size / 1024
        return self._row("SQLite Database", "GREEN", "READY", f"{DEFAULT_DB_PATH}; {size_kb:.1f} KiB", _file_updated_at(DEFAULT_DB_PATH), "OK")

    def _is_stale(self, updated_text: str) -> bool:
        if not updated_text:
            return True
        try:
            updated_at = pd.Timestamp(updated_text).to_pydatetime()
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=LOCAL_TZ)
            age_minutes = (datetime.now(LOCAL_TZ) - updated_at.astimezone(LOCAL_TZ)).total_seconds() / 60
            return age_minutes > self.daemon_stale_minutes
        except Exception:
            return True

    @staticmethod
    def _row(component: str, light: str, status: str, detail: str, updated_at: str, next_action: str) -> dict[str, str]:
        return {
            "light": light,
            "component": component,
            "status": status,
            "detail": detail,
            "updated_at": updated_at,
            "next_action": next_action,
        }


class DashboardBuilder:
    """Build a static local dashboard from paper-trading CSV files."""

    def __init__(self, output_dir: Path = Path("outputs")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build(self) -> Path:
        snapshot = self._load_snapshot()
        system_status = SystemStatusBuilder(self.output_dir).build()
        positions = self._read_csv("positions.csv")
        orders = self._read_csv("paper_order_log.csv").tail(10)
        trades = self._read_csv("paper_trade_log.csv").tail(10)
        decisions = self._read_csv("decision_log.csv").tail(10)
        performance = self._read_csv("local_performance_metrics.csv")
        allocation = self._read_csv("portfolio_allocation.csv")
        universe = self._read_csv("universe_summary.csv")
        universe_filter = self._read_csv("universe_filter.csv")
        factor_lab = self._read_csv("factor_lab_summary.csv")
        factor_latest = self._read_csv("factor_lab_latest_rank.csv")
        history = self._read_csv("account_history.csv")

        output_path = self.output_dir / "dashboard.html"
        output_path.write_text(
            self._render(
                snapshot,
                system_status,
                positions,
                orders,
                trades,
                decisions,
                performance,
                allocation,
                universe,
                universe_filter,
                factor_lab,
                factor_latest,
                history,
            ),
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
        system_status: pd.DataFrame,
        positions: pd.DataFrame,
        orders: pd.DataFrame,
        trades: pd.DataFrame,
        decisions: pd.DataFrame,
        performance: pd.DataFrame,
        allocation: pd.DataFrame,
        universe: pd.DataFrame,
        universe_filter: pd.DataFrame,
        factor_lab: pd.DataFrame,
        factor_latest: pd.DataFrame,
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
    <section style="margin-bottom:16px;">
      <h2>System Status</h2>
      {self._table(system_status)}
    </section>
    <div class="grid">
      <section><h2>Positions</h2>{self._table(positions)}</section>
      <section><h2>Recent Decisions</h2>{self._table(decisions)}</section>
      <section><h2>Recent Orders</h2>{self._table(orders)}</section>
      <section><h2>Recent Trades</h2>{self._table(trades)}</section>
      <section><h2>Performance Metrics</h2>{self._table(performance)}</section>
      <section><h2>Portfolio Allocation</h2>{self._table(allocation)}</section>
      <section><h2>Universe Summary</h2>{self._table(universe)}</section>
      <section><h2>Universe Filter</h2>{self._table(universe_filter)}</section>
      <section><h2>Factor Lab Summary</h2>{self._table(factor_lab)}</section>
      <section><h2>Factor Lab Latest Rank</h2>{self._table(factor_latest)}</section>
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


def _read_csv_path(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _file_updated_at(path: Path) -> str:
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime, LOCAL_TZ).isoformat(timespec="seconds")
