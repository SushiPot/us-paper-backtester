from __future__ import annotations

from src.framework_integration import FrameworkIntegrationReporter


def main() -> None:
    print("[START] framework_integration_main.py 已启动", flush=True)
    frame = FrameworkIntegrationReporter().run()
    print(f"[OK] 成熟框架集成路线已生成，项目数量={len(frame)}", flush=True)
    print("[OUTPUT] outputs/framework_integration_plan.csv", flush=True)
    print("[OUTPUT] outputs/framework_integration_plan.md", flush=True)


if __name__ == "__main__":
    main()
