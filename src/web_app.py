from __future__ import annotations

from pathlib import Path
from time import perf_counter
import json

import pandas as pd
from flask import Flask, abort, flash, jsonify, redirect, render_template_string, request, url_for

from .agents.manager import ManagerRunConfig, OverallManager
from .allocation_optimizer import PortfolioAllocationOptimizer
from .backtester import Backtester
from .cache_warmup import MarketCacheWarmup
from .config import BacktestConfig
from .config import LocalPaperConfig
from .config import build_market_data_config
from .dashboard import SystemStatusBuilder
from .data import MarketDataLoader
from .database import DEFAULT_DB_PATH
from .factor_lab import FactorLabAnalyzer
from .fundamental_data import FundamentalDataAnalyzer
from .indicators import add_indicators
from .local_paper_trader import LocalPaperTrader
from .macro_data import MacroDataAnalyzer
from .optimizer import ParameterOptimizer
from .performance import PerformanceReportBuilder
from .strategy_health import StrategyHealthAnalyzer
from .strategy_variant_evaluator import StrategyVariantEvaluator
from .self_optimizer import SelfOptimizationReporter
from .universe import UniverseFilter, filter_market_data_for_tradable
from .walk_forward import WalkForwardValidator
from .market_calendar import completed_session, get_us_market_session, next_session_open, now_new_york


REPORTS = {
    "predictions": ("Prediction Rank", "prediction/latest_predictions.csv", "head"),
    "quotes": ("Indicative Quotes", "prediction/market_quotes.csv", "head"),
    "execution": ("Execution Research", "prediction/execution_summary.csv", "head"),
    "execution-trades": ("Execution Trades", "prediction/execution_trades.csv", "tail"),
    "execution-equity": ("Execution Equity", "prediction/execution_equity.csv", "tail"),
    "validation": ("Model Validation", "prediction/model_comparison.csv", "head"),
    "prospective": ("Issued Forecast Outcomes", "prediction/issued_outcomes.csv", "tail"),
    "prospective-status": ("Forecast Eligibility", "prediction/prospective_inventory.csv", "tail"),
    "prospective-scores": ("Forward Evidence By Model", "prediction/prospective_scorecard.csv", "head"),
    "prospective-reliability": ("Forward Probability Reliability", "prediction/prospective_reliability.csv", "head"),
    "positions": ("Positions", "positions.csv", "head"),
    "decisions": ("Recent Decisions", "decision_log.csv", "tail"),
    "candidates": ("Candidate Rank", "candidate_rank.csv", "head"),
    "no-trade": ("No Trade Summary", "no_trade_summary.csv", "head"),
    "orders": ("Order History", "paper_order_log.csv", "tail"),
    "trades": ("Trade History", "paper_trade_log.csv", "tail"),
    "performance": ("Performance Metrics", "local_performance_metrics.csv", "head"),
    "data-health": ("Data Health", "data_health.csv", "head"),
    "data-summary": ("Data Health Summary", "data_health_summary.csv", "head"),
    "cache": ("Cache Warmup Summary", "cache_warmup_summary.csv", "head"),
    "cache-queue": ("Cache Warmup Queue", "cache_warmup_queue.csv", "head"),
    "cache-log": ("Cache Warmup Log", "cache_warmup_log.csv", "tail"),
    "market": ("Market Environment", "market_environment.csv", "head"),
    "market-summary": ("Market Environment Summary", "market_environment_summary.csv", "head"),
    "macro": ("Macro Indicators", "macro_indicators.csv", "head"),
    "macro-summary": ("Macro Environment Summary", "macro_environment_summary.csv", "head"),
    "benchmark": ("Benchmark Gate", "benchmark_gate.csv", "head"),
    "benchmark-summary": ("Benchmark Gate Summary", "benchmark_gate_summary.csv", "head"),
    "losses": ("Loss Attribution", "loss_attribution.csv", "head"),
    "loss-summary": ("Loss Attribution Summary", "loss_attribution_summary.csv", "head"),
    "signals": ("Signal Evaluation Detail", "signal_evaluation.csv", "head"),
    "signal-summary": ("Signal Evaluation Summary", "signal_evaluation_summary.csv", "head"),
    "strength": ("Relative Strength Rank", "relative_strength_rank.csv", "head"),
    "universe": ("Universe Filter", "universe_filter.csv", "head"),
    "universe-summary": ("Universe Summary", "universe_summary.csv", "head"),
    "factors": ("Factor Lab Summary", "factor_lab_summary.csv", "head"),
    "factor-rank": ("Factor Lab Rank", "factor_lab_latest_rank.csv", "head"),
    "factor-ic": ("Factor Lab Daily IC", "factor_lab_daily_ic.csv", "tail"),
    "factor-groups": ("Factor Lab Group Returns", "factor_lab_group_returns.csv", "tail"),
    "fundamentals": ("Fundamental Snapshot", "fundamental_snapshot.csv", "head"),
    "fundamental-summary": ("Fundamental Summary", "fundamental_summary.csv", "head"),
    "scorecard": ("Strategy Scorecard", "strategy_scorecard.csv", "head"),
    "backtest-scorecard": ("Backtest Scorecard", "backtest_strategy_scorecard.csv", "head"),
    "strategy-health": ("Strategy Health", "strategy_health.csv", "head"),
    "regime": ("Market Regime", "market_regime.csv", "head"),
    "walk-forward": ("Walk Forward Results", "walk_forward_results.csv", "head"),
    "walk-summary": ("Walk Forward Summary", "walk_forward_summary.csv", "head"),
    "variants": ("Strategy Variants", "strategy_variant_scores.csv", "head"),
    "adaptive": ("Adaptive Profile", "adaptive_strategy_profile.csv", "head"),
    "self-optimization": ("Optimization Actions", "self_optimization_actions.csv", "head"),
    "github": ("GitHub Candidates", "github_project_candidates.csv", "head"),
    "frameworks": ("Framework Integration", "framework_integration_plan.csv", "head"),
    "options": ("Options Research", "options_research_summary.csv", "head"),
    "options-liquidity": ("Options Liquidity", "options_liquidity_watchlist.csv", "head"),
    "online-allocation": ("Online Allocation", "online_portfolio_allocation.csv", "head"),
    "online-allocation-summary": ("Online Allocation Summary", "online_portfolio_allocation_summary.csv", "head"),
    "allocation": ("Portfolio Allocation", "portfolio_allocation.csv", "head"),
    "agents": ("Agent Run Log", "agent_run_log.csv", "tail"),
    "online-projects": ("Online Research Projects", "online_research_projects.csv", "head"),
    "optimization": ("Optimization Top 10", "optimization_top10.csv", "head"),
    "trained": ("Trained Backtest", "trained/backtest_report.csv", "head"),
}


def create_app(output_dir: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = "local-paper-web-ui"
    config = LocalPaperConfig()
    output_dir = Path(output_dir or config.output_dir)
    app.jinja_env.globals["table"] = _table

    @app.get("/")
    def index():
        report = _json_object(output_dir / "prediction/report.json")
        context = report.get("decision_context", {})
        if not isinstance(context, dict):
            context = {}
        status = _json_object(output_dir / "prediction/status.json")
        prospective = report.get("prospective", {})
        if not isinstance(prospective, dict):
            prospective = {}
        as_of = report.get("as_of", "N/A")
        action = context.get("action", "WAIT_FOR_FRESH_DATA")
        if (not report.get("data_ready") or status.get("status") in {"ERROR", "RUNNING"}
                or as_of != completed_session().date().isoformat()):
            action = "WAIT_FOR_FRESH_DATA"
        elif now_new_york() >= next_session_open(as_of):
            action = "WAIT_FOR_NEXT_CLOSE"
        snapshot = {
            "Daily Bars": as_of,
            "Expected Session": completed_session().date().isoformat(),
            "Decision": action.replace("_", " ").title(),
            "Model": report.get("model", "N/A"),
            "Forward Evidence": "Monitoring Only" if prospective.get("evidence_status") == "MONITORING_ONLY" else "Not Yet Verified",
            "Real Trading": "DISABLED",
        }
        predictions = _read_csv(output_dir / "prediction/latest_predictions.csv", limit=10)
        if not predictions.empty:
            predictions["decision"] = action
            predictions = predictions.reindex(columns=["symbol", "probability", "above_research_threshold", "decision", "price", "quote_at", "quote_status"])
            predictions = _expire_quotes(predictions)
            predictions["probability"] = predictions["probability"].map(lambda value: f"{value:.2%}" if pd.notna(value) else "N/A")
            predictions["price"] = predictions["price"].map(lambda value: f"${value:,.2f}" if pd.notna(value) else "N/A")
            predictions["decision"] = predictions["decision"].str.replace("_", " ").str.title()
            predictions = predictions.rename(columns={"symbol": "Symbol", "probability": "Probability", "above_research_threshold": "Above Threshold", "decision": "Decision", "price": "Indicative Price", "quote_at": "Quote Time (UTC)", "quote_status": "Quote Status"})
        tables = {"Prediction Rank": predictions}
        scores = _read_csv(output_dir / "prediction/prospective_scorecard.csv", limit=10)
        if not scores.empty:
            scores = scores.reindex(columns=["model_sha256", "dates", "rows", "classification_accuracy", "always_positive_accuracy", "ranked_signal_count", "ranked_signal_hit_rate", "evidence_status"])
            scores["model_sha256"] = scores.model_sha256.astype("string").str[:12]
            for column in ("classification_accuracy", "always_positive_accuracy", "ranked_signal_hit_rate"):
                scores[column] = pd.to_numeric(scores[column], errors="coerce").map(lambda value: f"{value:.2%}" if pd.notna(value) else "N/A")
            scores = scores.rename(columns={"model_sha256": "Model", "dates": "Mature Dates", "rows": "Forecasts",
                                           "classification_accuracy": "Net-Direction Accuracy", "always_positive_accuracy": "Always-Positive Baseline",
                                           "ranked_signal_count": "Ranked Signals", "ranked_signal_hit_rate": "Signal Hit Rate", "evidence_status": "Evidence"})
        tables["Forward Evidence By Model"] = scores
        positions = _read_csv(output_dir / config.positions_file, limit=100)
        if not positions.empty:
            tables["Existing Paper Positions"] = positions
        tables["Issued Forecast Outcomes"] = _read_csv(output_dir / "prediction/issued_outcomes.csv", limit=10, tail=True)
        return render_template_string(
            TEMPLATE, snapshot=snapshot, tables=tables, table_limit=10,
            page_title="Daily Forecasts", page_subtitle="RESEARCH ONLY", show_tools=False,
        )

    @app.get("/health")
    def health():
        return jsonify(service="us-paper-backtester", status="OK")

    @app.get("/advanced")
    def advanced():
        return render_template_string(
            TEMPLATE, snapshot={}, tables={}, catalog=REPORTS, table_limit=10,
            page_title="Advanced Research", page_subtitle="RESEARCH ONLY", show_tools=True,
        )

    @app.get("/reports/<report_id>")
    def report_page(report_id):
        if report_id not in REPORTS:
            abort(404)
        page = request.args.get("page", 1, type=int)
        if page < 1 or page > 10000:
            abort(400)
        title, relative, _ = REPORTS[report_id]
        frame, has_next = _csv_page(output_dir / relative, page)
        return render_template_string(
            TEMPLATE, snapshot={}, tables={title: frame}, table_limit=100,
            page_title=title, page_subtitle=f"Page {page}", show_tools=False,
            previous=url_for("report_page", report_id=report_id, page=page - 1) if page > 1 else None,
            following=url_for("report_page", report_id=report_id, page=page + 1) if has_next else None,
        )

    @app.post("/predict")
    def predict():
        from .prediction import run_prediction
        from .prediction_data import PredictionConfig

        try:
            result = run_prediction(PredictionConfig(output_dir=output_dir / "prediction"), refresh=True, daily=True)
        except (OSError, ValueError, RuntimeError) as exc:
            flash(f"Update failed: {type(exc).__name__}: {exc}. No orders were submitted.", "warning")
            return redirect(url_for("index"))
        flash(f"Daily bars: {result['as_of']}. {result['decision_context']['action']}. Real trading disabled.")
        return redirect(url_for("index"))

    @app.post("/checks")
    def checks():
        from .runtime_check import runtime_checks

        rows = runtime_checks(output_dir)
        return render_template_string(
            TEMPLATE, snapshot={}, tables={"Self Check": pd.DataFrame(rows)}, table_limit=100,
            page_title="Self Check", page_subtitle="OFFLINE", show_tools=False,
        )

    @app.post("/run-local")
    def run_local():
        start = perf_counter()
        LocalPaperTrader(config).run_once()
        flash(f"Local paper trading run completed in {perf_counter() - start:.1f}s.", "success")
        return redirect(url_for("index"))

    @app.post("/universe")
    def universe():
        start = perf_counter()
        frame = _run_universe(config, output_dir)
        passed = int(frame["tradable_passed"].map(_csv_bool).sum()) if not frame.empty else 0
        flash(
            f"Universe filter completed in {perf_counter() - start:.1f}s. "
            f"Tradable passed {passed}/{len(frame)}.",
            "success",
        )
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

    @app.post("/cache-warmup")
    def cache_warmup():
        start = perf_counter()
        result = MarketCacheWarmup(config, output_dir=output_dir).run()
        flash(
            (
                "Market cache warmup completed in "
                f"{perf_counter() - start:.1f}s. Status {result.status}: {result.message}."
            ),
            "success" if result.status == "OK" else "warning",
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
        factor_summary = _run_factor_lab(config, output_dir)
        walk_forward = WalkForwardValidator(BacktestConfig(), output_dir=output_dir).run()
        health = StrategyHealthAnalyzer(config, BacktestConfig()).run()
        factor_leader = factor_summary.iloc[0] if not factor_summary.empty else {}
        flash(
            (
                "Research outputs completed in "
                f"{perf_counter() - start:.1f}s. Allocation: {allocation.method}, "
                f"stock {allocation.stock_weight:.2%}, cash {allocation.cash_weight:.2%}. "
                f"Factor {factor_leader.get('factor_name', 'none')} "
                f"score {float(factor_leader.get('factor_score', 0.0)):.1f}. "
                f"Walk-forward {walk_forward.stability_score:.1f}. "
                f"Health {health.overall_score:.1f} ({health.health_status})."
            ),
            "success",
        )
        return redirect(url_for("index"))

    @app.post("/factor-lab")
    def factor_lab():
        start = perf_counter()
        summary = _run_factor_lab(config, output_dir)
        leader = summary.iloc[0] if not summary.empty else {}
        flash(
            (
                "Factor Lab completed in "
                f"{perf_counter() - start:.1f}s. Leader {leader.get('factor_name', 'none')} "
                f"score {float(leader.get('factor_score', 0.0)):.1f}, status {leader.get('status', '')}."
            ),
            "success",
        )
        return redirect(url_for("index"))

    return app


def _run_factor_lab(config: LocalPaperConfig, output_dir: Path) -> pd.DataFrame:
    data_config = build_market_data_config(config, output_dir=output_dir)
    raw_data = MarketDataLoader(data_config).download_all()
    market_data = {
        symbol: add_indicators(frame, config.fast_ma, config.slow_ma, config.rsi_period)
        for symbol, frame in raw_data.items()
    }
    UniverseFilter(config, output_dir).run(market_data)
    return FactorLabAnalyzer(config, output_dir).run(filter_market_data_for_tradable(market_data, output_dir))


def _run_universe(config: LocalPaperConfig, output_dir: Path) -> pd.DataFrame:
    data_config = build_market_data_config(config, output_dir=output_dir)
    raw_data = MarketDataLoader(data_config).download_all()
    return UniverseFilter(config, output_dir).run(raw_data)


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
        "Cache Warmup": _cache_warmup_status(output_dir),
        "Market Env": _market_environment_status(output_dir),
        "Benchmark Gate": _benchmark_gate_status(output_dir),
        "Loss State": _loss_state(output_dir),
        "Daemon": _daemon_status(output_dir),
    }


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _expire_quotes(frame: pd.DataFrame) -> pd.DataFrame:
    frame["quote_status"] = frame["quote_status"].astype(object)
    now = pd.Timestamp.now("UTC")
    regular = get_us_market_session(now_new_york()).is_regular_hours
    for index, value in frame["quote_at"].items():
        stamp = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(stamp):
            frame.loc[index, "quote_status"] = "MISSING"
        elif (stamp > now + pd.Timedelta(minutes=5)
              or stamp.tz_convert("America/New_York").date() < completed_session().date()
              or (regular and now - stamp > pd.Timedelta(minutes=30))):
            frame.loc[index, "quote_status"] = "STALE"
    return frame


def _csv_page(path: Path, page: int, page_size: int = 100) -> tuple[pd.DataFrame, bool]:
    start, stop = (page - 1) * page_size, page * page_size + 1
    rows, offset = [], 0
    try:
        with pd.read_csv(path, chunksize=2000) as reader:
            for chunk in reader:
                end = offset + len(chunk)
                if end > start:
                    rows.append(chunk.iloc[max(0, start - offset):max(0, stop - offset)])
                offset = end
                if offset >= stop:
                    break
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame(), False
    frame = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return frame.head(page_size), len(frame) > page_size


def _read_csv(path: Path, limit: int | None = None, tail: bool = False) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        if limit is not None and tail:
            result = pd.DataFrame()
            with pd.read_csv(path, chunksize=2000) as reader:
                for chunk in reader:
                    result = pd.concat([result, chunk]).tail(limit)
            return result
        return pd.read_csv(path, nrows=limit)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def _table(frame: pd.DataFrame, limit: int = 10) -> str:
    if frame.empty:
        return '<div class="empty">No data yet.</div>'
    frame = frame.head(limit).copy()
    return frame.to_html(index=False, classes="data-table", border=0, escape=True, na_rep="N/A")


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


def _cache_warmup_status(output_dir: Path) -> str:
    frame = _read_csv(output_dir / "cache_warmup_summary.csv")
    if frame.empty:
        return "N/A"
    row = frame.iloc[-1]
    status = str(_get(row, "status", "UNKNOWN"))
    fresh = int(float(_get(row, "fresh", 0)))
    total = int(float(_get(row, "total_symbols", 0)))
    return f"{status} {fresh}/{total}"


def _market_environment_status(output_dir: Path) -> str:
    frame = _read_csv(output_dir / "market_environment_summary.csv")
    if frame.empty:
        return "N/A"
    row = frame.iloc[-1]
    return f"{_get(row, 'market_status', '')}"


def _benchmark_gate_status(output_dir: Path) -> str:
    frame = _read_csv(output_dir / "benchmark_gate_summary.csv")
    if frame.empty:
        return "N/A"
    row = frame.iloc[-1]
    return f"{_get(row, 'status', '')} {_get(row, 'recommended_action', '')}"


def _loss_state(output_dir: Path) -> str:
    frame = _read_csv(output_dir / "loss_attribution_summary.csv")
    if frame.empty:
        return "N/A"
    row = frame.iloc[-1]
    total_return = float(_get(row, "total_return", 0.0))
    largest_loss = str(_get(row, "largest_loss_symbol", ""))
    suffix = f" {largest_loss}" if largest_loss else ""
    return f"{total_return:.2%}{suffix}"


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


def _csv_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


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
    .metric, .notice {
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
      font-size: 16px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .notice {
      padding: 10px 12px;
      margin-bottom: 16px;
      color: var(--accent-dark);
      background: #ecfdf3;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 16px;
    }
    section {
      padding: 16px 0;
      border-top: 1px solid var(--border);
      overflow: auto;
      min-width: 0;
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
        <div class="subtitle">{{ page_title }} / {{ page_subtitle }}</div>
      </div>
      <div class="actions">
        <form method="post" action="{{ url_for('predict') }}" onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').textContent='Updating...'"><button type="submit">Update Forecasts</button></form>
        <a class="link-button ghost" href="{{ url_for('index') }}">Results</a>
        <form method="post" action="{{ url_for('checks') }}"><button type="submit" class="ghost">Self Check</button></form>
        <a class="link-button ghost" href="{{ url_for('advanced') }}">Advanced</a>
      </div>
    </div>
  </header>
  <main>
      {% if show_tools %}
      <section><h2>Advanced Jobs</h2><div class="actions">
        <form method="post" action="{{ url_for('run_local') }}"><button type="submit">Run Local Paper</button></form>
        <form method="post" action="{{ url_for('manager') }}"><button type="submit" class="ghost">Run Manager</button></form>
        <form method="post" action="{{ url_for('manager_online') }}"><button type="submit" class="ghost">Run Online Manager</button></form>
        <form method="post" action="{{ url_for('manager_ai') }}"><button type="submit" class="ghost">Run AI Manager</button></form>
        <form method="post" action="{{ url_for('online_data') }}"><button type="submit" class="ghost">Refresh Online Data</button></form>
        <form method="post" action="{{ url_for('cache_warmup') }}"><button type="submit" class="ghost">Refresh Market Cache</button></form>
        <form method="post" action="{{ url_for('research') }}"><button type="submit" class="ghost">Run Research</button></form>
        <form method="post" action="{{ url_for('universe') }}"><button type="submit" class="ghost">Run Universe Filter</button></form>
        <form method="post" action="{{ url_for('factor_lab') }}"><button type="submit" class="ghost">Run Factor Lab</button></form>
        <form method="post" action="{{ url_for('self_optimize') }}"><button type="submit" class="ghost">Run Self Optimize</button></form>
        <form method="post" action="{{ url_for('walk_forward') }}"><button type="submit" class="ghost">Run Walk-Forward</button></form>
        <form method="post" action="{{ url_for('trained_backtest') }}"><button type="submit" class="ghost">Run Trained Backtest</button></form>
        <form method="post" action="{{ url_for('optimize') }}"><button type="submit" class="ghost">Run Optimizer</button></form>
      </div></section>
      {% endif %}
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
      {% if catalog %}
      <section><h2>Reports</h2><div class="actions">
        {% for key, item in catalog.items() %}
        <a class="link-button ghost" href="{{ url_for('report_page', report_id=key) }}">{{ item[0] }}</a>
        {% endfor %}
      </div></section>
      {% endif %}
      {% if equity_svg %}
      <section class="wide">
        <h2>Equity Curve</h2>
        <div class="chart">{{ equity_svg|safe }}</div>
      </section>
      {% endif %}
      {% for title, frame in tables.items() %}
        <section>
          <h2>{{ title }}</h2>
          {{ table(frame, table_limit)|safe }}
        </section>
      {% endfor %}
      {% if previous or following %}
      <nav class="actions" aria-label="Report pages">
        {% if previous %}<a class="link-button ghost" href="{{ previous }}">Previous</a>{% endif %}
        {% if following %}<a class="link-button ghost" href="{{ following }}">Next</a>{% endif %}
      </nav>
      {% endif %}
      <section class="wide">
        <h2>Safety</h2>
        <div class="ibkr-note">This web app only runs the local simulation. It does not connect to IBKR and does not place real or broker-side paper orders.</div>
      </section>
    </div>
  </main>
</body>
</html>
"""
