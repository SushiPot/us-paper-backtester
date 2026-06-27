from __future__ import annotations

import traceback

from src.walk_forward import WalkForwardValidator


def main() -> None:
    """运行 walk-forward 滚动训练/验证，只做模拟分析，不下单。"""
    summary = WalkForwardValidator().run()
    print("Walk-forward 验证完成")
    print(f"窗口数量: {summary.windows}")
    print(f"正收益验证窗口: {summary.positive_test_windows}")
    print(f"平均验证收益: {summary.avg_test_return:.2%}")
    print(f"平均验证夏普: {summary.avg_test_sharpe:.2f}")
    print(f"最差验证回撤: {summary.worst_test_drawdown:.2%}")
    print(f"稳定性评分: {summary.stability_score:.2f}")
    print(f"建议参数: {summary.recommended_params_label}")
    print(f"建议动作: {summary.recommended_action}")
    print("输出目录: outputs")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] walk_forward_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
