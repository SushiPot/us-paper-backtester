from __future__ import annotations

from src.market_environment import MarketEnvironmentAnalyzer


def main() -> None:
    print("[START] market_environment_main.py ???", flush=True)
    summary = MarketEnvironmentAnalyzer().run()
    status = str(summary.iloc[-1]["market_status"]) if not summary.empty else "NO_DATA"
    print(f"[OK] ???????? status={status}", flush=True)
    print("[OUTPUT] outputs/market_environment_summary.csv", flush=True)
    print("[OUTPUT] outputs/market_environment.csv", flush=True)


if __name__ == "__main__":
    main()
