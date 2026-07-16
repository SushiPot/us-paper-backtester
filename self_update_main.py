from __future__ import annotations

import argparse
import os
import subprocess
import sys
import traceback

from src.agents.manager import AgentMode
from src.cache_warmup import MarketCacheWarmup
from src.config import LocalPaperConfig
from src.dashboard import DashboardBuilder, SystemStatusBuilder
from src.daemon import AgentDaemon, DaemonConfig
from src.data_health import DataHealthChecker


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the safe daily self-update workflow.")
    parser.add_argument("--mode", choices=[mode.value for mode in AgentMode], default="online", help="daemon mode, default: online")
    parser.add_argument("--cache-limit", type=int, default=-1, help="max stale symbols to refresh; -1 means all stale symbols")
    parser.add_argument("--skip-tests", action="store_true", help="skip fast regression tests")
    parser.add_argument("--skip-daemon", action="store_true", help="skip daemon once maintenance")
    parser.add_argument("--skip-cache", action="store_true", help="skip full cache warmup after daemon")
    parser.add_argument("--skip-dashboard", action="store_true", help="skip dashboard.html regeneration")
    parser.add_argument(
        "--force-local-paper",
        action="store_true",
        help="force the local paper daemon job even during regular US market hours",
    )
    args = parser.parse_args()

    print("[START] self_update_main.py", flush=True)
    if not args.skip_tests:
        _run_step("fast regression tests", _run_tests)
    if not args.skip_daemon:
        _run_step("daemon once maintenance", lambda: _run_daemon(args.mode, args.force_local_paper))
    if not args.skip_cache:
        _run_step("market cache warmup", lambda: _run_cache(args.cache_limit))
    _run_step("data health refresh", _run_data_health)
    if not args.skip_dashboard:
        _run_step("dashboard refresh", _run_dashboard)
    _run_step("status summary", _print_status_summary)
    print("[END] self_update_main.py completed", flush=True)


def _run_step(name: str, callback) -> None:
    print(f"[STEP] {name}", flush=True)
    callback()


def _run_tests() -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, flush=True)
        if completed.stderr:
            print(completed.stderr, flush=True)
        raise RuntimeError(f"fast regression tests failed with exit code {completed.returncode}")
    print("[RESULT] tests=OK", flush=True)


def _run_daemon(mode: str, force_local_paper: bool) -> None:
    daemon = AgentDaemon(DaemonConfig(mode=AgentMode(mode)))
    force_job = "daily_local_paper" if force_local_paper else None
    results = daemon.run_once(force_job=force_job)
    print(f"[RESULT] daemon_jobs={len(results)}", flush=True)


def _run_cache(cache_limit: int) -> None:
    result = MarketCacheWarmup(LocalPaperConfig(), max_symbols=cache_limit).run()
    print(f"[RESULT] cache_status={result.status} message={result.message}", flush=True)


def _run_data_health() -> None:
    summary = DataHealthChecker().run()
    status = str(summary.iloc[-1]["status"]) if not summary.empty else "NO_DATA"
    print(f"[RESULT] data_health={status}", flush=True)


def _run_dashboard() -> None:
    output_path = DashboardBuilder().build()
    print(f"[RESULT] dashboard={output_path}", flush=True)


def _print_status_summary() -> None:
    status = SystemStatusBuilder().build()
    for row in status.to_dict(orient="records"):
        print(
            f"{row.get('light', ''):6} {row.get('component', ''):22} "
            f"{row.get('status', ''):12} {row.get('detail', '')}",
            flush=True,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] self_update_main.py failed: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
