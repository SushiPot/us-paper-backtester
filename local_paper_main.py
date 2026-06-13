import argparse
import sys
import traceback


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("[START] local_paper_main.py 已启动", flush=True)

from src.config import LocalPaperConfig
from src.local_paper_trader import LocalPaperTrader


def main() -> None:
    """本地模拟盘入口。不连接 IBKR，不需要券商账户。"""
    parser = argparse.ArgumentParser(description="本地美股模拟盘，一次运行一次决策")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    args = parser.parse_args()

    if not args.once:
        print("未指定 --once，将按兼容模式只运行一次。推荐使用: python local_paper_main.py --once", flush=True)

    config = LocalPaperConfig()
    trader = LocalPaperTrader(config)
    trader.run_once()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] local_paper_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
