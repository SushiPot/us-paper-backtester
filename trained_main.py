from pathlib import Path

from src.backtester import Backtester
from src.config import BacktestConfig


def main() -> None:
    """???????????????????????????"""
    config = BacktestConfig(
        fast_ma=30,
        slow_ma=60,
        rsi_period=14,
        rsi_limit=60.0,
        stop_loss_pct=-0.05,
        take_profit_pct=0.30,
        max_holding_days=30,
        output_dir=Path("outputs") / "trained",
    )
    report = Backtester(config).run()

    print("????????")
    print("??: MA30/MA60, RSI<60, SL=-5%, TP=30%, Hold=30")
    print(f"????: {report.total_return:.2%}")
    print(f"?????: {report.annual_return:.2%}")
    print(f"????: {report.max_drawdown:.2%}")
    print(f"????: {report.sharpe_ratio:.2f}")
    print(f"??: {report.win_rate:.2%}")
    print(f"????: {report.trade_count}")
    print("????: outputs/trained")


if __name__ == "__main__":
    main()
