import argparse
import os
import sys
import traceback

import pandas as pd


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("[START] local_paper_main.py 已启动", flush=True)

from src.agents.base import AgentContext
from src.agents.notification_agent import NotificationAgent
from src.config import LocalPaperConfig
from src.adaptive_config import apply_adaptive_profile
from src.local_paper_trader import LocalPaperTrader


def main() -> None:
    """本地模拟盘入口。不连接 IBKR，不需要券商账户。"""
    parser = argparse.ArgumentParser(description="本地美股模拟盘，一次运行一次决策")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--use-adaptive-profile", action="store_true", help="读取自我优化候选配置；默认受安全门控限制")
    parser.add_argument("--force-adaptive-profile", action="store_true", help="强制应用候选配置，仅用于本地模拟研究")
    parser.add_argument("--skip-email", action="store_true", help="跳过本地模拟盘运行后的邮件通知检查")
    args = parser.parse_args()

    if not args.once:
        print("未指定 --once，将按兼容模式只运行一次。推荐使用: python local_paper_main.py --once", flush=True)

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
    started_at = pd.Timestamp.now()
    trader = LocalPaperTrader(config)
    trader.run_once()
    if not args.skip_email:
        _send_local_notification_if_enabled(config, started_at)


def _send_local_notification_if_enabled(config: LocalPaperConfig, started_at: pd.Timestamp) -> None:
    """本地模拟盘直跑时复用 Manager 邮件条件；邮箱环境未启用则只提示。"""
    email_enabled = os.getenv("EMAIL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    if not email_enabled:
        print(
            "[INFO] EMAIL_ENABLED is false; local paper email notification skipped. "
            "Use run_local_paper_email.cmd or run_manager.cmd to load the saved QQ Mail profile.",
            flush=True,
        )
        return

    context = AgentContext(local_config=config, output_dir=config.output_dir)
    context.artifacts["manager_started_at"] = started_at
    result = NotificationAgent().run(context)
    print(f"[EMAIL] {result.status}: {result.message}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] local_paper_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
