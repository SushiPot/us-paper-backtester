from __future__ import annotations

import argparse

from src.notifier import EmailNotifier, build_manager_email_body


def main() -> None:
    parser = argparse.ArgumentParser(description="?????????????????")
    parser.add_argument("--send", action="store_true", help="???????????")
    args = parser.parse_args()

    print("[START] email_test_main.py ???", flush=True)
    notifier = EmailNotifier()
    body = build_manager_email_body()
    result = notifier.send("US Paper Backtester Email Test", body, force=args.send)
    print(f"[RESULT] status={result.status}", flush=True)
    print(f"[RESULT] recipient={result.recipient}", flush=True)
    print(f"[RESULT] message={result.message}", flush=True)
    if result.error:
        print(f"[ERROR] {result.error}", flush=True)
    print("[OUTPUT] outputs/notification_log.csv", flush=True)


if __name__ == "__main__":
    main()
