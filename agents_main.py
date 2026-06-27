from __future__ import annotations

import argparse
import sys
import traceback

from src.agents.manager import AgentMode, ManagerRunConfig, OverallManager


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    """Overall Manager ???? Agent ???????????"""
    parser = argparse.ArgumentParser(description="Overall Manager ? Agent ??/??????")
    parser.add_argument("--once", action="store_true", help="?????")
    parser.add_argument("--mode", choices=[mode.value for mode in AgentMode], default="local", help="????: local/online/ai")
    parser.add_argument("--online", action="store_true", help="??????????")
    parser.add_argument("--llm", action="store_true", help="?? OpenRouter ???? LLM ??")
    parser.add_argument("--skip-local-paper", action="store_true", help="?????????")
    parser.add_argument("--skip-research", action="store_true", help="?????????????")
    parser.add_argument("--stop-on-error", action="store_true", help="? Agent ???????")
    args = parser.parse_args()

    if not args.once:
        print("??? --once?????????????????: python agents_main.py --once", flush=True)

    mode = args.mode
    if args.llm:
        mode = AgentMode.AI.value
    elif args.online:
        mode = AgentMode.ONLINE.value

    config = ManagerRunConfig.for_mode(
        mode,
        run_local_paper=not args.skip_local_paper,
        run_research=not args.skip_research,
        stop_on_error=args.stop_on_error,
    )
    results = OverallManager(config).run_once()
    print("Overall Manager ????", flush=True)
    for result in results:
        print(f"- {result.agent}: {result.status} | {result.message}", flush=True)
    print("????: outputs/manager_report.md", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] agents_main.py ????: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
