from __future__ import annotations

from src.framework_integration import FrameworkIntegrationReporter


def main() -> None:
    print("[START] framework_integration_main.py ???", flush=True)
    frame = FrameworkIntegrationReporter().run()
    print(f"[OK] ????????????????={len(frame)}", flush=True)
    print("[OUTPUT] outputs/framework_integration_plan.csv", flush=True)
    print("[OUTPUT] outputs/framework_integration_plan.md", flush=True)


if __name__ == "__main__":
    main()
