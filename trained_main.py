from pathlib import Path

from src.backtester import Backtester
from src.config import BacktestConfig


def main() -> None:
    """运行训练后候选参数回测。当前版本仍然只做模拟，不下单。"""
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

    print("训练参数回测完成")
    print("参数: MA30/MA60, RSI<60, SL=-5%, TP=30%, Hold=30")
    print(f"总收益率: {report.total_return:.2%}")
    print(f"年化收益率: {report.annual_return:.2%}")
    print(f"最大回撤: {report.max_drawdown:.2%}")
    print(f"夏普比率: {report.sharpe_ratio:.2f}")
    print(f"胜率: {report.win_rate:.2%}")
    print(f"交易次数: {report.trade_count}")
    print("输出目录: outputs/trained")


if __name__ == "__main__":
    main()
