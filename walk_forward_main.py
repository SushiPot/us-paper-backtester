from __future__ import annotations

import traceback

from src.walk_forward import WalkForwardValidator


def main() -> None:
    """?? walk-forward ????/??????????????"""
    summary = WalkForwardValidator().run()
    print("Walk-forward ????")
    print(f"????: {summary.windows}")
    print(f"???????: {summary.positive_test_windows}")
    print(f"??????: {summary.avg_test_return:.2%}")
    print(f"??????: {summary.avg_test_sharpe:.2f}")
    print(f"??????: {summary.worst_test_drawdown:.2%}")
    print(f"?????: {summary.stability_score:.2f}")
    print(f"????: {summary.recommended_params_label}")
    print(f"????: {summary.recommended_action}")
    print("????: outputs")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] walk_forward_main.py ????: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
