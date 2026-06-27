from dataclasses import dataclass, field
from pathlib import Path
import os


def _env_bool(name: str, default: bool = False) -> bool:
    """读取布尔环境变量，避免配置在模块导入时固定住。"""
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """读取整数环境变量；填错时回退到默认值，避免启动时崩溃。"""
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError:
        return default


IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7497
IBKR_CLIENT_ID = 1
DRY_RUN = True
ALLOW_LIVE_TRADING = False

DEFAULT_SYMBOLS = ["TSLA", "NVDA", "AAPL", "SPY", "QQQ", "SPCX"]
WATCH_ONLY_SYMBOLS = ["SPCX"]
SPECIAL_MAX_POSITION_PCT = {
    # SPCX 作为 SpaceX 相关观察标的，上市/数据历史可能较短，先限制为半仓风险预算。
    "SPCX": 0.10,
}


@dataclass(frozen=True)
class BacktestConfig:
    """回测参数配置。"""

    symbols: list[str] = field(default_factory=lambda: DEFAULT_SYMBOLS.copy())
    watch_only_symbols: list[str] = field(default_factory=lambda: WATCH_ONLY_SYMBOLS.copy())
    start_date: str = "2018-01-01"
    end_date: str | None = None
    initial_cash: float = 10_000.0
    fast_ma: int = 20
    slow_ma: int = 60
    rsi_period: int = 14
    rsi_limit: float = 70.0
    enabled_buy_strategies: list[str] = field(default_factory=lambda: ["strict_golden_cross", "trend_follow"])
    trend_min_rsi: float = 45.0
    trend_volume_ratio: float = 0.80
    trend_max_distance_fast_ma: float = 0.08
    trend_min_return_5d: float = -0.03
    trend_position_scale: float = 0.40
    enable_market_environment_gate: bool = True
    enable_macro_environment_gate: bool = True
    enable_strategy_health_gate: bool = True
    enable_benchmark_gate: bool = True
    enable_relative_strength_filter: bool = True
    benchmark_symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    benchmark_gate_min_observations: int = 5
    benchmark_underperformance_reduce_pct: float = -0.01
    benchmark_underperformance_pause_pct: float = -0.03
    relative_strength_top_n: int = 3
    neutral_relative_strength_top_n: int = 2
    observation_relative_strength_top_n: int = 1
    relative_strength_min_score: float = 70.0
    observation_relative_strength_min_score: float = 80.0
    signal_eval_horizons: list[int] = field(default_factory=lambda: [5, 10, 20])
    signal_eval_positive_return_threshold: float = 0.03
    max_position_pct: float = 0.20
    special_max_position_pct: dict[str, float] = field(default_factory=lambda: SPECIAL_MAX_POSITION_PCT.copy())
    max_positions: int = 5
    stop_loss_pct: float = -0.08
    take_profit_pct: float = 0.20
    max_holding_days: int = 30
    enable_dynamic_exit: bool = True
    neutral_stop_loss_pct: float = -0.03
    risk_off_stop_loss_pct: float = -0.02
    trailing_stop_pct: float = -0.05
    stagnant_exit_days: int = 5
    stagnant_exit_max_return_pct: float = 0.0
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

    symbols: list[str] = field(default_factory=lambda: DEFAULT_SYMBOLS.copy())
    watch_only_symbols: list[str] = field(default_factory=lambda: WATCH_ONLY_SYMBOLS.copy())
    ibkr_host: str = IBKR_HOST
    ibkr_port: int = IBKR_PORT
    ibkr_client_id: int = IBKR_CLIENT_ID
    ibkr_connect_timeout_seconds: float = 10.0
    dry_run: bool = DRY_RUN
    allow_live_trading: bool = ALLOW_LIVE_TRADING
    paper_account_prefix: str = "DU"
    market_data_type: int = 3
    max_position_pct: float = 0.20
    special_max_position_pct: dict[str, float] = field(default_factory=lambda: SPECIAL_MAX_POSITION_PCT.copy())
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

    symbols: list[str] = field(default_factory=lambda: DEFAULT_SYMBOLS.copy())
    watch_only_symbols: list[str] = field(default_factory=lambda: WATCH_ONLY_SYMBOLS.copy())
    initial_cash: float = 10_000.0
    fast_ma: int = 20
    slow_ma: int = 60
    rsi_period: int = 14
    rsi_limit: float = 70.0
    enabled_buy_strategies: list[str] = field(default_factory=lambda: ["strict_golden_cross", "trend_follow"])
    trend_min_rsi: float = 45.0
    trend_volume_ratio: float = 0.80
    trend_max_distance_fast_ma: float = 0.08
    trend_min_return_5d: float = -0.03
    trend_position_scale: float = 0.40
    enable_market_environment_gate: bool = True
    enable_macro_environment_gate: bool = True
    enable_strategy_health_gate: bool = True
    enable_benchmark_gate: bool = True
    enable_relative_strength_filter: bool = True
    benchmark_symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    benchmark_gate_min_observations: int = 5
    benchmark_underperformance_reduce_pct: float = -0.01
    benchmark_underperformance_pause_pct: float = -0.03
    relative_strength_top_n: int = 3
    neutral_relative_strength_top_n: int = 2
    observation_relative_strength_top_n: int = 1
    relative_strength_min_score: float = 70.0
    observation_relative_strength_min_score: float = 80.0
    signal_eval_horizons: list[int] = field(default_factory=lambda: [5, 10, 20])
    signal_eval_positive_return_threshold: float = 0.03
    max_position_pct: float = 0.20
    special_max_position_pct: dict[str, float] = field(default_factory=lambda: SPECIAL_MAX_POSITION_PCT.copy())
    max_positions: int = 5
    stop_loss_pct: float = -0.08
    take_profit_pct: float = 0.20
    max_holding_days: int = 30
    enable_dynamic_exit: bool = True
    neutral_stop_loss_pct: float = -0.03
    risk_off_stop_loss_pct: float = -0.02
    trailing_stop_pct: float = -0.05
    stagnant_exit_days: int = 5
    stagnant_exit_max_return_pct: float = 0.0
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
    allow_multiple_risk_reducing_sells: bool = True
    retry_count: int = 3
    retry_wait_seconds: float = 2.0


@dataclass(frozen=True)
class EmailConfig:
    """邮箱通知配置。所有敏感信息只从环境变量读取，不写入代码。"""

    enabled: bool = field(default_factory=lambda: _env_bool("EMAIL_ENABLED", False))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _env_int("SMTP_PORT", 587))
    smtp_username: str = field(default_factory=lambda: os.getenv("SMTP_USERNAME", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    email_from: str = field(default_factory=lambda: os.getenv("EMAIL_FROM", os.getenv("SMTP_USERNAME", "")))
    email_to: str = field(default_factory=lambda: os.getenv("EMAIL_TO", ""))
    use_tls: bool = field(default_factory=lambda: _env_bool("SMTP_USE_TLS", True))
    output_dir: Path = Path("outputs")
    notification_log_file: str = "notification_log.csv"


@dataclass(frozen=True)
class OptionsResearchConfig:
    """股票/期权研究配置。只做数据分析，不下单。"""

    symbols: list[str] = field(default_factory=lambda: ["TSLA", "NVDA", "AAPL", "SPY", "QQQ"])
    output_dir: Path = Path("outputs")
    max_expirations_per_symbol: int = 3
    min_open_interest: int = 50
    max_spread_pct: float = 0.25
    moneyness_window_pct: float = 0.20
    include_puts: bool = True
    include_calls: bool = True


@dataclass(frozen=True)
class MacroDataConfig:
    """免费宏观数据配置。使用 FRED 公开 CSV，不需要 API key。"""

    series: dict[str, str] = field(
        default_factory=lambda: {
            "VIXCLS": "CBOE Volatility Index",
            "DGS10": "10-Year Treasury Constant Maturity Rate",
            "DGS2": "2-Year Treasury Constant Maturity Rate",
            "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury",
            "FEDFUNDS": "Effective Federal Funds Rate",
            "UNRATE": "Unemployment Rate",
            "CPIAUCSL": "Consumer Price Index",
            "SP500": "S&P 500 Index",
        }
    )
    output_dir: Path = Path("outputs")
    timeout_seconds: float = 20.0
    retry_count: int = 2
    retry_wait_seconds: float = 1.5


@dataclass(frozen=True)
class FundamentalDataConfig:
    """免费 SEC EDGAR 基本面数据配置。只读取公开披露，不需要 API key。"""

    cik_by_symbol: dict[str, str] = field(
        default_factory=lambda: {
            "AAPL": "0000320193",
            "NVDA": "0001045810",
            "TSLA": "0001318605",
        }
    )
    output_dir: Path = Path("outputs")
    timeout_seconds: float = 20.0
    retry_count: int = 2
    retry_wait_seconds: float = 1.5
    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "us-paper-backtester/1.0 local-research@example.com")
