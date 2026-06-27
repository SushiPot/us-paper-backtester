import argparse
import sys
import traceback


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("[START] local_paper_main.py ???", flush=True)

from src.config import LocalPaperConfig
from src.adaptive_config import apply_adaptive_profile
from src.local_paper_trader import LocalPaperTrader


def main() -> None:
    """??????????? IBKR?????????"""
    parser = argparse.ArgumentParser(description="????????????????")
    parser.add_argument("--once", action="store_true", help="?????")
    parser.add_argument("--use-adaptive-profile", action="store_true", help="????????????????????")
    parser.add_argument("--force-adaptive-profile", action="store_true", help="??????????????????")
    args = parser.parse_args()

    if not args.once:
        print("??? --once?????????????????: python local_paper_main.py --once", flush=True)

    config = LocalPaperConfig()
    if args.use_adaptive_profile or args.force_adaptive_profile:
        config, profile = apply_adaptive_profile(config, force=args.force_adaptive_profile)
        print(
            "[ADAPTIVE] "
            f"profile={profile.get('profile_name', '')} "
            f"applied={profile.get('applied', False)} "
            f"gate={profile.get('gate_status', '')} "
            f"reason={profile.get('reason', '')}",
            flush=True,
        )
    trader = LocalPaperTrader(config)
    trader.run_once()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] local_paper_main.py ????: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
