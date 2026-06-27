import argparse
import sys
import traceback


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("[START] paper_main.py ???", flush=True)

from src.config import PaperTradingConfig
from src.run_monitor import RunMonitor


def main() -> None:
    """IBKR Paper Trading ???????????? dry_run=True???????"""
    print("[STATUS] ?????????", flush=True)
    parser = argparse.ArgumentParser(description="IBKR Paper Trading ???????")
    parser.add_argument("--once", action="store_true", help="???????????????")
    parser.add_argument("--yes", action="store_true", help="???? YES ???????")
    args = parser.parse_args()
    print(f"[STATUS] ??????: once={args.once}, yes={args.yes}", flush=True)

    if not args.once:
        print("??? --once?????????????????: python paper_main.py --once", flush=True)

    print("[STATUS] ???? PaperTradingConfig", flush=True)
    config = PaperTradingConfig()
    print(
        f"[STATUS] ??????: DRY_RUN={config.dry_run}, "
        f"ALLOW_LIVE_TRADING={config.allow_live_trading}, "
        f"HOST={config.ibkr_host}, PORT={config.ibkr_port}, CLIENT_ID={config.ibkr_client_id}",
        flush=True,
    )
    print("[STATUS] ???? RunMonitor", flush=True)
    monitor = RunMonitor(config, assume_yes=args.yes)
    print("[STATUS] RunMonitor ????????? run_once()", flush=True)
    monitor.run_once()
    print("[END] paper_main.py ????", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] paper_main.py ????: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
