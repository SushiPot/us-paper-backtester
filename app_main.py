"""Standalone entry point for the daily workflow and optional research tools."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def _ours(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
            return json.load(response).get("service") == "us-paper-backtester"
    except (OSError, ValueError, AttributeError):
        return False


def show_results(open_browser: bool = True) -> str:
    import socket

    for port in range(5000, 5011):
        if _ours(port):
            break
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                continue
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        with (log_dir / "web.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "web_app.py"), "--port", str(port)], cwd=ROOT,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        for _ in range(80):
            if _ours(port):
                output = ROOT / "outputs"
                output.mkdir(exist_ok=True)
                (output / "web_server.json").write_text(json.dumps({"launcher_pid": process.pid, "port": port}), encoding="utf-8")
                break
            if process.poll() is not None:
                raise RuntimeError("Results server failed; see logs/web.log")
            time.sleep(0.25)
        else:
            process.terminate()
            process.wait(timeout=5)
            raise RuntimeError("Results server startup timed out; see logs/web.log")
        break
    else:
        raise RuntimeError("No free results port in 5000-5010")
    url = f"http://127.0.0.1:{port}"
    print(f"[RESULTS] {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    return url


def main() -> int:
    os.chdir(ROOT)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Daily forecasts, results and self check. Real trading remains disabled.")
    parser.add_argument("command", nargs="?", choices=("run", "view", "check", "research", "advanced"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--full", action="store_true", help="run full tests with check")
    args = parser.parse_args()
    command = args.command
    if command is None:
        print("1. Update forecasts\n2. View results\n3. Self check\n4. Advanced research\n0. Exit")
        command = {"1": "run", "2": "view", "3": "check", "4": "advanced"}.get(input("Select: ").strip())
    if command == "check":
        if args.full:
            return subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
        from src.runtime_check import print_checks
        return print_checks()
    if command in {"run", "research"}:
        from src.prediction import run_prediction
        result = run_prediction(refresh=True, daily=command == "run")
        print(f"[REPORT] {ROOT / 'outputs/prediction/report.md'}", flush=True)
        return 0 if result["data_ready"] else 2
    if command in {"view", "advanced"}:
        url = show_results(open_browser=False)
        if not args.no_browser:
            webbrowser.open(url + ("/advanced" if command == "advanced" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
