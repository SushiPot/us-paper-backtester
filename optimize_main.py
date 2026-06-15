from src.optimizer import ParameterOptimizer


def main() -> None:
    """Run a lightweight parameter sweep for the current strategy family."""
    optimizer = ParameterOptimizer()
    best = optimizer.run()
    print("Optimization complete")
    print(f"Best params: {best.params_label}")
    print(f"Total return: {best.total_return:.2%}")
    print(f"Max drawdown: {best.max_drawdown:.2%}")
    print(f"Sharpe ratio: {best.sharpe_ratio:.2f}")
    print(f"Trades: {best.trade_count}")


if __name__ == "__main__":
    main()
