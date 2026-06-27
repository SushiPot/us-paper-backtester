from __future__ import annotations

from src.options_research import OptionsResearchScanner


def main() -> None:
    print("[START] options_research_main.py 已启动", flush=True)
    result = OptionsResearchScanner().run()
    print(f"[OK] 期权研究扫描完成，合约数={result.contract_count}", flush=True)
    print(f"[OK] 流动性观察合约数={result.liquid_contract_count}", flush=True)
    print(f"[OUTPUT] {result.output_file}", flush=True)
    print("[SAFETY] 研究用途，不生成订单，不连接券商", flush=True)


if __name__ == "__main__":
    main()
