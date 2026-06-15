from dataclasses import dataclass, field
from pathlib import Path


IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7497
IBKR_CLIENT_ID = 1
DRY_RUN = True
ALLOW_LIVE_TRADING = False


@dataclass(frozen=True)
class BacktestConfig:
    """回测参数配置。"""

    symbols: list[str] = field(default_factory=lambda: ["TSLA", "NVDA", "AAPL", "SPY", "QQQ"])
    start_date: str = "2018-01-01"
    end_date: str | None = None
    initial_cash: float = 10_000.0
    fast_ma: int = 20
    slow_ma: int = 60
    rsi_period: int = 14
    rsi_limit: float = 70.0
    max_position_pct: float = 0.20
    max_positions: int = 5
    stop_loss_pct: float = -0.08
    take_profit_pct: float = 0.20
    max_holding_days: int = 30
    daily_loss_limit_pct: float = -0.02
    max_account_drawdown_pct: float = -0.10
    output_dir: Path = Path("outputs")
    trade_log_file: str = "trade_log.csv"
    risk_log_file: str = "risk_log.csv"
    report_file: str = "backtest_report.csv"
    equity_curve_csv_file: str = "equity_curve.csv"
    performance_metrics_file: str = "performance_metrics.csv"
    performance_report_file: str = "performance_report.html"
    equity_curve_file: str = "equity_curve.png"
    cache_dir: Path = Path("data_cache")
    cache_max_age_hours: float = 12.0
    yfinance_timeout_seconds: float = 10.0
    retry_count: int = 3
    retry_wait_seconds: float = 5.0


@dataclass(frozen=True)
class PaperTradingConfig:
    """IBKR Paper Trading 参数配置。默认只演练订单，不发送到 IBKR。"""

    symbols: list[str] = field(default_factory=lambda: ["TSLA", "NVDA", "AAPL", "SPY", "QQQ"])
    ibkr_host: str = IBKR_HOST
    ibkr_port: int = IBKR_PORT
    ibkr_client_id: int = IBKR_CLIENT_ID
    ibkr_connect_timeout_seconds: float = 10.0
    dry_run: bool = DRY_RUN
    allow_live_trading: bool = ALLOW_LIVE_TRADING
    paper_account_prefix: str = "DU"
    market_data_type: int = 3
    max_position_pct: float = 0.20
    max_positions: int = 5
    stop_loss_pct: float = -0.08
    take_profit_pct: float = 0.20
    max_holding_days: int = 30
    daily_loss_limit_pct: float = -0.02
    max_account_drawdown_pct: float = -0.10
    enforce_regular_trading_hours: bool = True
    historical_start_date: str = "2018-01-01"
    output_dir: Path = Path("outputs")
    paper_trade_log_file: str = "paper_trade_log.csv"
    paper_order_log_file: str = "paper_order_log.csv"
    paper_risk_log_file: str = "paper_risk_log.csv"
    paper_position_state_file: str = "paper_position_state.csv"
    run_log_file: str = "run_log.csv"
    decision_log_file: str = "decision_log.csv"
    safety_log_file: str = "safety_log.csv"
    max_price_change_pct: float = 0.30
    retry_count: int = 3
    retry_wait_seconds: float = 2.0


@dataclass(frozen=True)
class LocalPaperConfig:
    """不依赖券商账户的本地模拟盘配置。"""

    symbols: list[str] = field(default_factory=lambda: ["TSLA", "NVDA", "AAPL", "SPY", "QQQ"])
    initial_cash: float = 10_000.0
    fast_ma: int = 20
    slow_ma: int = 60
    rsi_period: int = 14
    rsi_limit: float = 70.0
    max_position_pct: float = 0.20
    max_positions: int = 5
    stop_loss_pct: float = -0.08
    take_profit_pct: float = 0.20
    max_holding_days: int = 30
    daily_loss_limit_pct: float = -0.02
    max_account_drawdown_pct: float = -0.10
    historical_start_date: str = "2018-01-01"
    output_dir: Path = Path("outputs")
    positions_file: str = "positions.csv"
    virtual_account_file: str = "virtual_account.csv"
    account_history_file: str = "account_history.csv"
    paper_order_log_file: str = "paper_order_log.csv"
    paper_trade_log_file: str = "paper_trade_log.csv"
    decision_log_file: str = "decision_log.csv"
    run_log_file: str = "run_log.csv"
    local_report_file: str = "local_paper_report.csv"
    local_performance_metrics_file: str = "local_performance_metrics.csv"
    local_performance_report_file: str = "local_performance_report.html"
    local_equity_curve_file: str = "local_equity_curve.png"
    max_price_change_pct: float = 0.30
    slippage_pct: float = 0.0005
    commission_per_share: float = 0.005
    min_commission: float = 1.0
    allow_one_order_per_run: bool = True
    retry_count: int = 3
    retry_wait_seconds: float = 2.0
