from __future__ import annotations

import argparse
import sys
import traceback

from src.agents.manager import ManagerRunConfig, OverallManager


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    """Overall Manager 入口：多 Agent 协作练习，不连接券商。"""
    parser = argparse.ArgumentParser(description="Overall Manager 多 Agent 本地/联网练习模式")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--online", action="store_true", help="启用联网公开项目扫描")
    parser.add_argument("--skip-local-paper", action="store_true", help="跳过本地模拟盘运行")
    parser.add_argument("--skip-research", action="store_true", help="跳过研究报告和组合权重刷新")
    parser.add_argument("--stop-on-error", action="store_true", help="子 Agent 出错时立即停止")
    args = parser.parse_args()

    if not args.once:
        print("未指定 --once，将按兼容模式只运行一次。推荐使用: python agents_main.py --once", flush=True)

    config = ManagerRunConfig(
        run_local_paper=not args.skip_local_paper,
        run_research=not args.skip_research,
        run_online_research=args.online,
        stop_on_error=args.stop_on_error,
    )
    results = OverallManager(config).run_once()
    print("Overall Manager 运行完成", flush=True)
    for result in results:
        print(f"- {result.agent}: {result.status} | {result.message}", flush=True)
    print("输出文件: outputs/manager_report.md", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] agents_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
