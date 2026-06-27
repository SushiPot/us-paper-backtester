from src.backtester import Backtester
from src.config import BacktestConfig


def main() -> None:
    """????????????????????"""
    config = BacktestConfig()
    backtester = Backtester(config)
    report = backtester.run()

    print("????")
    print(f"????: {report.total_return:.2%}")
    print(f"?????: {report.annual_return:.2%}")
    print(f"????: {report.max_drawdown:.2%}")
    print(f"????: {report.sharpe_ratio:.2f}")
    print(f"??: {report.win_rate:.2%}")
    print(f"?????: {report.avg_profit_loss_ratio:.2f}")
    print(f"????: {report.trade_count}")
    print("????: outputs")


if __name__ == "__main__":
    main()
