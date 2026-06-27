from __future__ import annotations

import argparse
import sys
import traceback

from src.cache_warmup import MarketCacheWarmup
from src.config import LocalPaperConfig


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    """渐进式补齐行情缓存，不连接券商，不下单。"""
    parser = argparse.ArgumentParser(description="US Paper Backtester 行情缓存预热")
    parser.add_argument("--limit", type=int, default=None, help="本次最多补多少只股票；-1 表示不限制，0 表示只检查")
    args = parser.parse_args()

    result = MarketCacheWarmup(LocalPaperConfig(), max_symbols=args.limit).run()
    print(f"[RESULT] status={result.status}", flush=True)
    print(f"[RESULT] message={result.message}", flush=True)
    print("[OUTPUT] outputs/cache_warmup_summary.csv", flush=True)
    print("[OUTPUT] outputs/cache_warmup_log.csv", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] cache_warmup_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
