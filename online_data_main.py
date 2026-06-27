import sys
import traceback


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("[START] online_data_main.py 已启动", flush=True)

from src.fundamental_data import FundamentalDataAnalyzer
from src.macro_data import MacroDataAnalyzer


def main() -> None:
    """刷新免费联网数据：FRED 宏观数据 + SEC EDGAR 基本面数据。"""
    macro = MacroDataAnalyzer().run()
    fundamentals = FundamentalDataAnalyzer().run()

    macro_row = macro.iloc[-1] if not macro.empty else {}
    fundamental_row = fundamentals.iloc[-1] if not fundamentals.empty else {}
    print(
        "[RESULT] macro="
        f"{macro_row.get('macro_status', 'NO_DATA')} "
        f"action={macro_row.get('recommended_action', '')}",
        flush=True,
    )
    print(
        "[RESULT] fundamentals="
        f"{fundamental_row.get('status', 'NO_DATA')} "
        f"metrics_ok={fundamental_row.get('metrics_ok', 0)}",
        flush=True,
    )
    print("[OUTPUT] outputs/macro_indicators.csv", flush=True)
    print("[OUTPUT] outputs/macro_environment_summary.csv", flush=True)
    print("[OUTPUT] outputs/fundamental_snapshot.csv", flush=True)
    print("[OUTPUT] outputs/fundamental_summary.csv", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] online_data_main.py 发生异常: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
