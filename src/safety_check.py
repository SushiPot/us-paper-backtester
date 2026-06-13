from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import PaperTradingConfig
from .ibkr_client import AccountSnapshot, PositionSnapshot
from .market_calendar import is_regular_us_market_hours, is_us_market_trading_day, now_new_york


@dataclass(frozen=True)
class StartupSafetySnapshot:
    """运行前确认界面所需信息。"""

    account: AccountSnapshot
    positions: dict[str, PositionSnapshot]
    is_paper_account: bool
    is_trading_day: bool
    is_regular_hours: bool
    dry_run: bool
    allow_live_trading: bool


@dataclass(frozen=True)
class SafetyResult:
    """安全检查结果。"""

    allowed: bool
    reason: str


def build_startup_snapshot(
    config: PaperTradingConfig,
    account: AccountSnapshot,
    positions: dict[str, PositionSnapshot],
) -> StartupSafetySnapshot:
    """构建运行前快照，不做下单。"""
    return StartupSafetySnapshot(
        account=account,
        positions=positions,
        is_paper_account=account.account.upper().startswith(config.paper_account_prefix),
        is_trading_day=is_us_market_trading_day(),
        is_regular_hours=is_regular_us_market_hours(),
        dry_run=config.dry_run,
        allow_live_trading=config.allow_live_trading,
    )


def validate_startup(config: PaperTradingConfig, snapshot: StartupSafetySnapshot) -> SafetyResult:
    """启动前硬性安全门。任意失败都退出。"""
    print("[CHECK] 安全检查: 今日是否美股交易日", flush=True)
    print(f"[RESULT] 今日是否美股交易日: {snapshot.is_trading_day}", flush=True)
    if not snapshot.is_trading_day:
        return SafetyResult(False, "今日不是美股交易日，程序退出")

    print("[CHECK] 安全检查: 当前是否美股正常交易时间", flush=True)
    print(f"[RESULT] 当前是否美股正常交易时间: {snapshot.is_regular_hours}", flush=True)
    if not snapshot.is_regular_hours:
        return SafetyResult(False, "当前不是美股正常交易时间，程序退出")

    print("[CHECK] 安全检查: 账户是否 DU Paper Account", flush=True)
    print(f"[RESULT] 账户是否 Paper Account: {snapshot.is_paper_account}", flush=True)
    if not snapshot.is_paper_account:
        return SafetyResult(False, "账户不是 DU 开头的 Paper Account，程序退出")

    print("[CHECK] 安全检查: ALLOW_LIVE_TRADING 是否为 False", flush=True)
    print(f"[RESULT] ALLOW_LIVE_TRADING: {snapshot.allow_live_trading}", flush=True)
    if snapshot.allow_live_trading:
        return SafetyResult(False, "ALLOW_LIVE_TRADING=True，程序退出")

    print("[CHECK] 安全检查: DRY_RUN 和 Paper Account 组合", flush=True)
    print(f"[RESULT] DRY_RUN={config.dry_run}, is_paper_account={snapshot.is_paper_account}", flush=True)
    if not config.dry_run and not snapshot.is_paper_account:
        return SafetyResult(False, "非 Paper Account 禁止发送订单")

    print("[OK] 启动安全检查全部通过", flush=True)
    return SafetyResult(True, "启动前安全检查通过")


def print_startup_confirmation(snapshot: StartupSafetySnapshot) -> None:
    """打印运行前确认界面。"""
    print("=" * 64)
    print("IBKR Paper Trading 运行前确认")
    print("=" * 64)
    print(f"纽约时间: {now_new_york():%Y-%m-%d %H:%M:%S %Z}")
    print(f"当前账户号: {snapshot.account.account}")
    print(f"是否 Paper Account: {snapshot.is_paper_account}")
    print(f"当前 DRY_RUN 状态: {snapshot.dry_run}")
    print(f"当前 ALLOW_LIVE_TRADING 状态: {snapshot.allow_live_trading}")
    print(f"当前现金: {snapshot.account.cash:.2f}")
    print(f"可用资金: {snapshot.account.available_funds:.2f}")
    print(f"账户权益: {snapshot.account.net_liquidation:.2f}")
    print(f"今日是否美股交易日: {snapshot.is_trading_day}")
    print(f"当前是否美股正常交易时间: {snapshot.is_regular_hours}")
    print("当前持仓:")
    if not snapshot.positions:
        print("  无持仓")
    else:
        for position in snapshot.positions.values():
            print(
                f"  {position.symbol}: {position.quantity} 股, "
                f"均价 {position.avg_cost:.2f}, 估值 {position.market_value:.2f}"
            )
    print("=" * 64)


def append_safety_log(output_dir: Path, filename: str, event_type: str, message: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    row = pd.DataFrame(
        [
            {
                "时间": pd.Timestamp.now(),
                "事件类型": event_type,
                "内容": message,
            }
        ]
    )
    row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
