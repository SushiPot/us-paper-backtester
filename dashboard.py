from src.dashboard import DashboardBuilder


def main() -> None:
    """Generate a local HTML dashboard from CSV outputs."""
    dashboard = DashboardBuilder()
    output_path = dashboard.build()
    print(f"Dashboard generated: {output_path}")


if __name__ == "__main__":
    main()
