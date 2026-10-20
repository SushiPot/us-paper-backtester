"""Offline, reproducible model comparisons; separate from the daily predictor."""
import argparse
from pathlib import Path

from src.prediction_experiments import run_experiments


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=Path("config/prediction_experiment_v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/prediction/experiments"))
    args = parser.parse_args()
    result = run_experiments(args.protocol, args.output_dir)
    print(f"[EXPERIMENT] {result['status']}; {result['report_path']}")
