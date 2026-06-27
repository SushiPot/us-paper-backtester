import argparse
import sys
import traceback


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("[START] paper_main.py 已启动", flush=True)

from src.config import PaperTradingConfig
from src.run_monitor import RunMonitor


def main() -> None:
    """IBKR Paper Trading 一次性安全监控入口。默认 dry_run=True，不发送订单。"""
    print("[STATUS] 开始解析命令行参数", flush=True)
    parser = argparse.ArgumentParser(description="IBKR Paper Trading 一次性安全监控")
    parser.add_argument("--once", action="store_true", help="只运行一次，只生成一次订单决策")
    parser.add_argument("--yes", action="store_true", help="跳过人工 YES 确认，谨慎使用")
    args = parser.parse_args()
    print(f"[STATUS] 参数解析完成: once={args.once}, yes={args.yes}", flush=True)

    if not args.once:
        print("未指定 --once，将按兼容模式只运行一次。推荐使用: python paper_main.py --once", flush=True)

    print("[STATUS] 开始加载 PaperTradingConfig", flush=True)
    config = PaperTradingConfig()
    print(
        f"[STATUS] 配置加载完成: DRY_RUN={config.dry_run}, "
        f"ALLOW_LIVE_TRADING={config.allow_live_trading}, "
        f"HOST={config.ibkr_host}, PORT={config.ibkr_port}, CLIENT_ID={config.ibkr_client_id}",
        flush=True,
    )
    print("[STATUS] 开始创建 RunMonitor", flush=True)
    monitor = RunMonitor(config, assume_yes=args.yes)
    print("[STATUS] RunMonitor 创建完成，准备进入 run_once()", flush=True)
    monitor.run_once()
    print("[END] paper_main.py 正常结束", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] paper_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
