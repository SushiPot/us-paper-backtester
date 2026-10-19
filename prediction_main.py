from __future__ import annotations

import argparse
from dataclasses import replace
import sys

from src.prediction import run_prediction
from src.prediction_data import PredictionConfig


def main():
    parser = argparse.ArgumentParser(description="Train and evaluate an isolated, chronological stock prediction study.")
    parser.add_argument("--refresh", action="store_true", help="refresh verified adjusted history before training")
    parser.add_argument("--max-downloads", type=int, default=60)
    parser.add_argument("--symbols", nargs="+", help="explicit research universe; SPY is always loaded as benchmark")
    args = parser.parse_args()
    config = PredictionConfig()
    if args.symbols:
        config = replace(config, symbols=tuple(symbol.upper() for symbol in args.symbols))
    run_prediction(config, refresh=args.refresh, max_downloads=max(0, args.max_downloads))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
