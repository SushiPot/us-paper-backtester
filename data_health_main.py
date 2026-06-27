from __future__ import annotations

from src.data_health import DataHealthChecker


def main() -> None:
    print("[START] data_health_main.py ???", flush=True)
    summary = DataHealthChecker().run()
    status = str(summary.iloc[-1]["status"]) if not summary.empty else "NO_DATA"
    print(f"[OK] ???????? status={status}", flush=True)
    print("[OUTPUT] outputs/data_health_summary.csv", flush=True)
    print("[OUTPUT] outputs/data_health.csv", flush=True)


if __name__ == "__main__":
    main()
