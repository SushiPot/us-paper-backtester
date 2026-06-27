from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import LocalPaperConfig
from .database import get_store


class LossAttributionReporter:
    """????????????????????????????????"""

    def __init__(self, config: LocalPaperConfig | None = None, output_dir: Path = Path("outputs")) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, account: dict[str, float | str], positions: dict[str, object]) -> pd.DataFrame:
        rows = self._position_rows(positions)
        frame = pd.DataFrame(rows)
        if frame.empty:
            frame = pd.DataFrame(
                columns=[
                    "time",
                    "component",
                    "symbol",
                    "strategy_name",
                    "quantity",
                    "market_value",
                    "pnl",
                    "return_pct",
                    "share_of_gross_exposure",
                    "note",
                ]
            )

        total_open_pnl = float(frame["pnl"].sum()) if "pnl" in frame.columns and not frame.empty else 0.0
        equity = float(account.get("equity", 0.0))
        total_pnl = equity - self.config.initial_cash
        estimated_realized_or_fees = total_pnl - total_open_pnl
        summary = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "equity": equity,
                    "initial_cash": self.config.initial_cash,
                    "total_pnl": total_pnl,
                    "total_return": equity / self.config.initial_cash - 1 if self.config.initial_cash else 0.0,
                    "open_unrealized_pnl": total_open_pnl,
                    "estimated_realized_pnl_or_costs": estimated_realized_or_fees,
                    "cash": float(account.get("virtual_cash", 0.0)),
                    "cash_pct": float(account.get("virtual_cash", 0.0)) / equity if equity else 0.0,
                    "open_position_count": len(positions),
                    "largest_loss_symbol": self._largest_loss_symbol(frame),
                }
            ]
        )

        frame.to_csv(self.output_dir / "loss_attribution.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(self.output_dir / "loss_attribution_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame, summary)
        store = get_store()
        store.append_generic_frame("loss_attribution", "loss_attribution.csv", frame)
        store.append_generic_frame("loss_attribution_summary", "loss_attribution_summary.csv", summary)
        return summary

    def _position_rows(self, positions: dict[str, object]) -> list[dict[str, object]]:
        rows = []
        for position in positions.values():
            quantity = int(getattr(position, "quantity", 0))
            avg_cost = float(getattr(position, "avg_cost", 0.0))
            last_price = float(getattr(position, "last_price", avg_cost))
            market_value = float(getattr(position, "market_value", quantity * last_price))
            pnl = (last_price - avg_cost) * quantity
            rows.append(
                {
                    "time": pd.Timestamp.now(),
                    "component": "open_position",
                    "symbol": str(getattr(position, "symbol", "")),
                    "strategy_name": str(getattr(position, "strategy_name", "unknown")),
                    "quantity": quantity,
                    "market_value": market_value,
                    "pnl": pnl,
                    "return_pct": last_price / avg_cost - 1 if avg_cost else 0.0,
                    "share_of_gross_exposure": 0.0,
                    "note": "unrealized open-position PnL",
                }
            )
        gross_exposure = sum(float(row["market_value"]) for row in rows)
        if gross_exposure:
            for row in rows:
                row["share_of_gross_exposure"] = float(row["market_value"]) / gross_exposure
        return sorted(rows, key=lambda item: float(item["pnl"]))

    @staticmethod
    def _largest_loss_symbol(frame: pd.DataFrame) -> str:
        if frame.empty or "pnl" not in frame.columns:
            return ""
        row = frame.sort_values("pnl").iloc[0]
        return str(row.get("symbol", ""))

    def _write_report(self, frame: pd.DataFrame, summary: pd.DataFrame) -> None:
        row = summary.iloc[0] if not summary.empty else {}
        lines = [
            "# Loss Attribution Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            f"- Total PnL: {float(row.get('total_pnl', 0.0)):.2f}",
            f"- Total return: {float(row.get('total_return', 0.0)):.2%}",
            f"- Open unrealized PnL: {float(row.get('open_unrealized_pnl', 0.0)):.2f}",
            f"- Estimated realized PnL / costs: {float(row.get('estimated_realized_pnl_or_costs', 0.0)):.2f}",
            f"- Largest open loss symbol: {row.get('largest_loss_symbol', '')}",
            "",
            "| symbol | strategy | quantity | market_value | pnl | return_pct |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in frame.to_dict(orient="records"):
            lines.append(
                f"| {item.get('symbol', '')} | {item.get('strategy_name', '')} | "
                f"{item.get('quantity', 0)} | {float(item.get('market_value', 0.0)):.2f} | "
                f"{float(item.get('pnl', 0.0)):.2f} | {float(item.get('return_pct', 0.0)):.2%} |"
            )
        (self.output_dir / "loss_attribution_report.md").write_text("\n".join(lines), encoding="utf-8")
