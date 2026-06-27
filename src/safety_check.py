from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import PaperTradingConfig
from .ibkr_client import AccountSnapshot, PositionSnapshot
from .market_calendar import get_us_market_session, now_new_york


@dataclass(frozen=True)
class StartupSafetySnapshot:
    """????????????"""

    account: AccountSnapshot
    positions: dict[str, PositionSnapshot]
    is_paper_account: bool
    is_trading_day: bool
    is_regular_hours: bool
    calendar_source: str
    market_open: str
    market_close: str
    dry_run: bool
    allow_live_trading: bool


@dataclass(frozen=True)
class SafetyResult:
    """???????"""

    allowed: bool
    reason: str


def build_startup_snapshot(
    config: PaperTradingConfig,
    account: AccountSnapshot,
    positions: dict[str, PositionSnapshot],
) -> StartupSafetySnapshot:
    """?????????????"""
    session = get_us_market_session()
    return StartupSafetySnapshot(
        account=account,
        positions=positions,
        is_paper_account=account.account.upper().startswith(config.paper_account_prefix),
        is_trading_day=session.is_trading_day,
        is_regular_hours=session.is_regular_hours,
        calendar_source=session.source,
        market_open=session.market_open.strftime("%Y-%m-%d %H:%M:%S %Z") if session.market_open else "",
        market_close=session.market_close.strftime("%Y-%m-%d %H:%M:%S %Z") if session.market_close else "",
        dry_run=config.dry_run,
        allow_live_trading=config.allow_live_trading,
    )


def validate_startup(config: PaperTradingConfig, snapshot: StartupSafetySnapshot) -> SafetyResult:
    """?????????????????"""
    print("[CHECK] ????: ?????????", flush=True)
    print(f"[RESULT] ?????????: {snapshot.is_trading_day}", flush=True)
    if not snapshot.is_trading_day:
        return SafetyResult(False, "??????????????")

    print("[CHECK] ????: ????????????", flush=True)
    print(f"[RESULT] ????????????: {snapshot.is_regular_hours}", flush=True)
    if not snapshot.is_regular_hours:
        return SafetyResult(False, "?????????????????")

    print("[CHECK] ????: ???? DU Paper Account", flush=True)
    print(f"[RESULT] ???? Paper Account: {snapshot.is_paper_account}", flush=True)
    if not snapshot.is_paper_account:
        return SafetyResult(False, "???? DU ??? Paper Account?????")

    print("[CHECK] ????: ALLOW_LIVE_TRADING ??? False", flush=True)
    print(f"[RESULT] ALLOW_LIVE_TRADING: {snapshot.allow_live_trading}", flush=True)
    if snapshot.allow_live_trading:
        return SafetyResult(False, "ALLOW_LIVE_TRADING=True?????")

    print("[CHECK] ????: DRY_RUN ? Paper Account ??", flush=True)
    print(f"[RESULT] DRY_RUN={config.dry_run}, is_paper_account={snapshot.is_paper_account}", flush=True)
    if not config.dry_run and not snapshot.is_paper_account:
        return SafetyResult(False, "? Paper Account ??????")

    print("[OK] ??????????", flush=True)
    return SafetyResult(True, "?????????")


def print_startup_confirmation(snapshot: StartupSafetySnapshot) -> None:
    """??????????"""
    print("=" * 64)
    print("IBKR Paper Trading ?????")
    print("=" * 64)
    print(f"????: {now_new_york():%Y-%m-%d %H:%M:%S %Z}")
    print(f"?????: {snapshot.account.account}")
    print(f"?? Paper Account: {snapshot.is_paper_account}")
    print(f"?? DRY_RUN ??: {snapshot.dry_run}")
    print(f"?? ALLOW_LIVE_TRADING ??: {snapshot.allow_live_trading}")
    print(f"????: {snapshot.account.cash:.2f}")
    print(f"????: {snapshot.account.available_funds:.2f}")
    print(f"????: {snapshot.account.net_liquidation:.2f}")
    print(f"?????????: {snapshot.is_trading_day}")
    print(f"????????????: {snapshot.is_regular_hours}")
    print(f"??????: {snapshot.calendar_source}")
    print(f"??????: {snapshot.market_open or 'N/A'}")
    print(f"??????: {snapshot.market_close or 'N/A'}")
    print("????:")
    if not snapshot.positions:
        print("  ???")
    else:
        for position in snapshot.positions.values():
            print(
                f"  {position.symbol}: {position.quantity} ?, "
                f"?? {position.avg_cost:.2f}, ?? {position.market_value:.2f}"
            )
    print("=" * 64)


def append_safety_log(output_dir: Path, filename: str, event_type: str, message: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    row = pd.DataFrame(
        [
            {
                "??": pd.Timestamp.now(),
                "????": event_type,
                "??": message,
            }
        ]
    )
    row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
