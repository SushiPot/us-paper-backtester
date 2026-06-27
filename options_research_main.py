from __future__ import annotations

from src.options_research import OptionsResearchScanner


def main() -> None:
    print("[START] options_research_main.py ???", flush=True)
    result = OptionsResearchScanner().run()
    print(f"[OK] ????????????={result.contract_count}", flush=True)
    print(f"[OK] ????????={result.liquid_contract_count}", flush=True)
    print(f"[OUTPUT] {result.output_file}", flush=True)
    print("[SAFETY] ????????????????", flush=True)


if __name__ == "__main__":
    main()
