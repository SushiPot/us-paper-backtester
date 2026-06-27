from __future__ import annotations

from src.config import LocalPaperConfig
from src.strategy_scorecard import StrategyScorecardBuilder


def main() -> None:
    print("[START] strategy_scorecard_main.py ???", flush=True)
    frame = StrategyScorecardBuilder(LocalPaperConfig()).run()
    print(f"[OK] ?????????????={len(frame)}", flush=True)
    print("[OUTPUT] outputs/strategy_scorecard.csv", flush=True)
    print("[OUTPUT] outputs/strategy_scorecard_report.md", flush=True)


if __name__ == "__main__":
    main()
