from src.backtester import Backtester
from src.config import BacktestConfig


def main() -> None:
    """回测入口。当前版本禁止任何真实交易接口。"""
    config = BacktestConfig()
    backtester = Backtester(config)
    report = backtester.run()

    print("回测完成")
    print(f"总收益率: {report.total_return:.2%}")
    print(f"年化收益率: {report.annual_return:.2%}")
    print(f"最大回撤: {report.max_drawdown:.2%}")
    print(f"夏普比率: {report.sharpe_ratio:.2f}")
    print(f"胜率: {report.win_rate:.2%}")
    print(f"平均盈亏比: {report.avg_profit_loss_ratio:.2f}")
    print(f"交易次数: {report.trade_count}")
    print("输出目录: outputs")


if __name__ == "__main__":
    main()
