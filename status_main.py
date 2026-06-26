import csv
import json
import subprocess
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("[START] status_main.py 已启动", flush=True)

from src.dashboard import SystemStatusBuilder


OUTPUT_DIR = Path("outputs")


def main() -> None:
    """打印项目当前状态，方便日常检查。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SystemStatusBuilder(OUTPUT_DIR).build()

    print("")
    print("=== Git 状态 ===")
    _print_command(["git", "status", "--short", "--branch"])

    print("")
    print("=== 系统状态灯 ===")
    for row in _read_csv(OUTPUT_DIR / "dashboard_status.csv"):
        print(
            f"{row.get('light', ''):6} "
            f"{row.get('component', ''):22} "
            f"{row.get('status', ''):12} "
            f"{row.get('detail', '')}"
        )

    print("")
    print("=== 虚拟账户 ===")
    account = _last_row(OUTPUT_DIR / "virtual_account.csv")
    report = _last_row(OUTPUT_DIR / "local_paper_report.csv")
    if account:
        print(f"日期: {account.get('as_of_date', '')}")
        print(f"现金: {_money(account.get('virtual_cash', 0))}")
        print(f"权益: {_money(account.get('equity', 0))}")
    if report:
        print(f"总收益率: {_pct(report.get('total_return', 0))}")
        print(f"最大回撤: {_pct(report.get('max_drawdown', 0))}")
        print(f"夏普: {_float_text(report.get('sharpe_ratio', 0), 2)}")
        print(f"持仓数量: {report.get('open_positions', 0)}")

    print("")
    print("=== 当前持仓 ===")
    positions = _read_csv(OUTPUT_DIR / "positions.csv")
    if not positions:
        print("无持仓")
    else:
        for row in positions:
            print(
                f"{row.get('symbol', '')}: "
                f"{row.get('quantity', '')} 股, "
                f"现价 {row.get('last_price', '')}, "
                f"浮动收益 {_pct(row.get('unrealized_return_pct', 0))}"
            )

    print("")
    print("=== Daemon ===")
    daemon = _read_json(OUTPUT_DIR / "agent_status.json")
    if daemon:
        print(f"状态: {daemon.get('status', '')}")
        print(f"消息: {daemon.get('message', '')}")
        print(f"更新时间: {daemon.get('local_time') or daemon.get('updated_at', '')}")
    else:
        print("无 daemon 状态文件")

    print("")
    print("[END] status_main.py 正常结束", flush=True)


def _print_command(command: list[str]) -> None:
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        output = (completed.stdout or completed.stderr).strip()
        print(output if output else "(no output)")
    except Exception as exc:
        print(f"命令失败: {type(exc).__name__}: {exc}")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _last_row(path: Path) -> dict[str, str]:
    rows = _read_csv(path)
    return rows[-1] if rows else {}


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _money(value) -> str:
    return f"${float(value):,.2f}"


def _pct(value) -> str:
    return f"{float(value):.2%}"


def _float_text(value, digits: int) -> str:
    return f"{float(value):.{digits}f}"


if __name__ == "__main__":
    main()
