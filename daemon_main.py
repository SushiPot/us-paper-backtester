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
    """24 ????????????? online ?????????"""
    parser = argparse.ArgumentParser(description="US Paper Backtester 24??????")
    parser.add_argument("--once", action="store_true", help="????????????")
    parser.add_argument("--mode", choices=[mode.value for mode in AgentMode], default="online", help="daemon ??: local/online/ai??? online")
    parser.add_argument("--loop-seconds", type=int, default=900, help="????????????? 900 ?")
    parser.add_argument(
        "--force-job",
        choices=["daily_local_paper", "daily_risk_check", "weekly_research", "daily_online_scan"],
        help="?????????????????",
    )
    parser.add_argument("--disable-online-scan", action="store_true", help="?? mode=online/ai ??????????")
    parser.add_argument("--disable-weekly-research", action="store_true", help="????????")
    parser.add_argument("--stop-on-error", action="store_true", help="Agent ???? manager ???? agent")
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
        print("????: outputs/agent_status.json", flush=True)
        print("????: logs/daemon.log", flush=True)
        return

    daemon.run_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[STOP] daemon_main.py ?? Ctrl+C????", flush=True)
    except Exception as exc:
        print(f"[ERROR] daemon_main.py ????: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
