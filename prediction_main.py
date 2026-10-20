from __future__ import annotations

import argparse
from dataclasses import replace
import sys

from src.prediction import run_prediction
from src.prediction_data import PredictionConfig


def main():
    parser = argparse.ArgumentParser(description="Update daily forecasts; run full historical research only on request.")
    parser.add_argument("--refresh", action="store_true", help="refresh verified adjusted history before training")
    parser.add_argument("--max-downloads", type=int, default=60)
    parser.add_argument("--research", action="store_true", help="run full historical evaluation and execution sensitivity checks")
    parser.add_argument("--retrain", action="store_true", help="force model fitting even when verified training inputs are unchanged")
    parser.add_argument("--symbols", nargs="+", help="explicit research universe; SPY is always loaded as benchmark")
    args = parser.parse_args()
    config = PredictionConfig()
    if args.symbols:
        config = replace(config, symbols=tuple(symbol.upper() for symbol in args.symbols))
    result = run_prediction(config, refresh=args.refresh, max_downloads=max(0, args.max_downloads),
                            daily=not args.research, retrain=args.retrain)
    return 0 if result["data_ready"] else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
