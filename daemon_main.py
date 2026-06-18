from __future__ import annotations

import argparse
import sys
import traceback

from src.agents.manager import AgentMode
from src.daemon import AgentDaemon, DaemonConfig


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    """24 小时自动团队入口。默认只运行本地模拟和研究流程，不连接券商。"""
    parser = argparse.ArgumentParser(description="US Paper Backtester 24小时自动团队")
    parser.add_argument("--once", action="store_true", help="只检查并运行一次到期任务")
    parser.add_argument("--mode", choices=[mode.value for mode in AgentMode], default="local", help="daemon 模式: local/online/ai")
    parser.add_argument("--loop-seconds", type=int, default=900, help="常驻模式每轮检查间隔，默认 900 秒")
    parser.add_argument(
        "--force-job",
        choices=["daily_local_paper", "daily_risk_check", "weekly_research", "daily_online_scan"],
        help="忽略到期判断，强制运行一个指定任务",
    )
    parser.add_argument("--disable-online-scan", action="store_true", help="即使 mode=online/ai 也不运行每日联网扫描")
    parser.add_argument("--disable-weekly-research", action="store_true", help="禁用每周研究任务")
    parser.add_argument("--stop-on-error", action="store_true", help="Agent 出错时让 manager 停止后续 agent")
    args = parser.parse_args()

    daemon = AgentDaemon(
        DaemonConfig(
            mode=AgentMode(args.mode),
            loop_seconds=args.loop_seconds,
            stop_on_error=args.stop_on_error,
            enable_online_scan=not args.disable_online_scan,
            enable_weekly_research=not args.disable_weekly_research,
        )
    )

    if args.once or args.force_job:
        results = daemon.run_once(force_job=args.force_job)
        print(f"[END] daemon_main.py once completed jobs={len(results)}", flush=True)
        print("输出文件: outputs/agent_status.json", flush=True)
        print("日志文件: logs/daemon.log", flush=True)
        return

    daemon.run_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[STOP] daemon_main.py 收到 Ctrl+C，已退出", flush=True)
    except Exception as exc:
        print(f"[ERROR] daemon_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
