"""Register the current verified model for a separate frozen forward study."""
import argparse

from src.prediction_shadow import register_shadow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", action="store_true", required=True,
                        help="freeze the current verified model once; never fit or replace it")
    parser.parse_args()
    record = register_shadow()
    print(f"[SHADOW] Registered {record['protocol']['protocol']}: {record['files']['model.joblib']}")
    print("Future daily runs collect shadow evidence automatically; real trading remains disabled.")


if __name__ == "__main__":
    main()
