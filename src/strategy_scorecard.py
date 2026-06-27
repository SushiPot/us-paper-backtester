from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import LocalPaperConfig
from .database import get_store


INVALID_STRATEGY_NAMES = {"", "none", "nan", "disabled", "unattributed", "unknown", "true", "false"}


@dataclass
class _OpenLot:
    """???????????????????????"""

    quantity: int
    cost_per_share: float


class StrategyScorecardBuilder:
    """???????????????????????"""

    def __init__(self, config: LocalPaperConfig | None = None, output_dir: Path | None = None) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir or self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> pd.DataFrame:
        decisions = _read_csv(self.output_dir / self.config.decision_log_file)
        orders = _read_csv(self.output_dir / self.config.paper_order_log_file)
        trades = _read_csv(self.output_dir / self.config.paper_trade_log_file)
        positions = _read_csv(self.output_dir / self.config.positions_file)

        decisions = self._normalize_strategy(decisions)
        orders = self._normalize_strategy(orders)
        trades = self._normalize_strategy(trades)
        positions = self._normalize_strategy(positions)
        positions = self._backfill_position_strategies(positions, trades)

        strategies = self._collect_strategies(decisions, orders, trades, positions)
        rows = []
        realized = self._realized_pnl_by_strategy(trades)

        for strategy_name in sorted(strategies):
            decision_slice = self._filter(decisions, strategy_name)
            order_slice = self._filter(orders, strategy_name)
            trade_slice = self._filter(trades, strategy_name)
            position_slice = self._filter(positions, strategy_name)

            realized_pnl = realized.get(strategy_name, 0.0)
            unrealized_pnl = self._unrealized_pnl(position_slice)
            total_pnl = realized_pnl + unrealized_pnl
            buy_fills = trade_slice[trade_slice.get("action", pd.Series(dtype=str)).astype(str).str.upper() == "BUY"]
            sell_fills = trade_slice[trade_slice.get("action", pd.Series(dtype=str)).astype(str).str.upper() == "SELL"]
            trade_returns = self._closed_trade_returns(trade_slice)
            win_rate = float((trade_returns > 0).mean()) if len(trade_returns) else 0.0
            avg_win = float(trade_returns[trade_returns > 0].mean()) if (trade_returns > 0).any() else 0.0
            avg_loss = float(abs(trade_returns[trade_returns < 0].mean())) if (trade_returns < 0).any() else 0.0
            avg_profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
            rejected_count = int(order_slice.get("status", pd.Series(dtype=str)).astype(str).str.upper().eq("REJECTED").sum())
            submitted_count = int(decision_slice.get("order_submitted", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
            decision_count = int(len(decision_slice))
            signal_count = int(decision_slice.get("signal_type", pd.Series(dtype=str)).astype(str).isin(["BUY", "SELL"]).sum())
            score = self._score(
                decision_count=decision_count,
                signal_count=signal_count,
                submitted_count=submitted_count,
                rejected_count=rejected_count,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                win_rate=win_rate,
            )

            rows.append(
                {
                    "strategy_name": strategy_name,
                    "decision_count": decision_count,
                    "buy_signal_count": int(decision_slice.get("signal_type", pd.Series(dtype=str)).astype(str).eq("BUY").sum()),
                    "sell_signal_count": int(decision_slice.get("signal_type", pd.Series(dtype=str)).astype(str).eq("SELL").sum()),
                    "submitted_decision_count": submitted_count,
                    "order_count": int(len(order_slice)),
                    "rejected_order_count": rejected_count,
                    "buy_fill_count": int(len(buy_fills)),
                    "sell_fill_count": int(len(sell_fills)),
                    "open_position_count": int(len(position_slice)),
                    "open_market_value": round(float(position_slice.get("market_value", pd.Series(dtype=float)).fillna(0).astype(float).sum()), 2),
                    "realized_pnl": round(realized_pnl, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "total_pnl": round(total_pnl, 2),
                    "win_rate": round(win_rate, 4),
                    "avg_profit_loss_ratio": round(avg_profit_loss_ratio, 4),
                    "avg_signal_score": round(float(decision_slice.get("signal_score", pd.Series(dtype=float)).fillna(0).astype(float).mean()), 2)
                    if not decision_slice.empty
                    else 0.0,
                    "strategy_score": round(score, 2),
                    "status": self._status(decision_count, len(buy_fills), len(sell_fills), score),
                }
            )

        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values(["strategy_score", "total_pnl", "decision_count"], ascending=[False, False, False])
        frame.to_csv(self.output_dir / "strategy_scorecard.csv", index=False, encoding="utf-8-sig")
        self._write_report(frame)
        get_store().append_generic_frame("strategy_scorecard", "strategy_scorecard.csv", frame)
        return frame

    @staticmethod
    def _normalize_strategy(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        normalized = frame.copy()
        if "strategy_name" not in normalized.columns:
            normalized["strategy_name"] = ""
        normalized["strategy_name"] = normalized.apply(_strategy_from_row, axis=1)
        if "signal_score" not in normalized.columns:
            normalized["signal_score"] = 0.0
        normalized["signal_score"] = pd.to_numeric(normalized["signal_score"], errors="coerce").fillna(0.0)
        return normalized

    @staticmethod
    def _collect_strategies(*frames: pd.DataFrame) -> set[str]:
        strategies: set[str] = set()
        for frame in frames:
            if frame.empty or "strategy_name" not in frame.columns:
                continue
            strategies.update(
                str(value)
                for value in frame["strategy_name"].dropna().tolist()
                if _is_valid_strategy_name(value)
            )
        return strategies or {"unattributed"}

    @staticmethod
    def _filter(frame: pd.DataFrame, strategy_name: str) -> pd.DataFrame:
        if frame.empty or "strategy_name" not in frame.columns:
            return pd.DataFrame()
        return frame[frame["strategy_name"].astype(str) == strategy_name]

    @staticmethod
    def _backfill_position_strategies(positions: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
        if positions.empty or trades.empty or "symbol" not in positions.columns:
            return positions
        lookup = _open_strategy_by_symbol(trades)
        if not lookup:
            return positions
        updated = positions.copy()
        for index, row in updated.iterrows():
            symbol = str(row.get("symbol", ""))
            current = str(row.get("strategy_name", "")).strip().lower()
            inferred = lookup.get(symbol)
            if not inferred:
                continue
            if current in {"", "nan", "none", "unknown", "unattributed"}:
                updated.at[index, "strategy_name"] = inferred.get("strategy_name", "unattributed")
            if _number(row.get("signal_score", 0.0), 0.0) == 0.0:
                updated.at[index, "signal_score"] = inferred.get("signal_score", 0.0)
        return updated

    @staticmethod
    def _realized_pnl_by_strategy(trades: pd.DataFrame) -> dict[str, float]:
        realized = defaultdict(float)
        lots: dict[tuple[str, str], deque[_OpenLot]] = defaultdict(deque)
        if trades.empty:
            return dict(realized)

        for _, row in trades.iterrows():
            strategy_name = str(row.get("strategy_name", "unattributed"))
            symbol = str(row.get("symbol", ""))
            action = str(row.get("action", "")).upper()
            quantity = _number(row.get("quantity", 0), 0)
            fill_price = _number(row.get("fill_price", 0.0), 0.0)
            commission = _number(row.get("commission", 0.0), 0.0)
            if quantity <= 0 or fill_price <= 0 or not symbol:
                continue

            key = (strategy_name, symbol)
            if action == "BUY":
                lots[key].append(_OpenLot(int(quantity), fill_price + commission / quantity))
            elif action == "SELL":
                remaining = int(quantity)
                proceeds_per_share = fill_price - commission / quantity
                while remaining > 0 and lots[key]:
                    lot = lots[key][0]
                    matched = min(remaining, lot.quantity)
                    realized[strategy_name] += matched * (proceeds_per_share - lot.cost_per_share)
                    lot.quantity -= matched
                    remaining -= matched
                    if lot.quantity <= 0:
                        lots[key].popleft()
        return dict(realized)

    @staticmethod
    def _closed_trade_returns(trades: pd.DataFrame) -> pd.Series:
        if trades.empty:
            return pd.Series(dtype=float)
        returns = []
        lots: dict[str, deque[float]] = defaultdict(deque)
        for _, row in trades.iterrows():
            action = str(row.get("action", "")).upper()
            symbol = str(row.get("symbol", ""))
            quantity = int(_number(row.get("quantity", 0), 0))
            fill_price = _number(row.get("fill_price", 0.0), 0.0)
            if not symbol or quantity <= 0 or fill_price <= 0:
                continue
            if action == "BUY":
                for _ in range(quantity):
                    lots[symbol].append(fill_price)
            elif action == "SELL":
                for _ in range(quantity):
                    if not lots[symbol]:
                        break
                    cost = lots[symbol].popleft()
                    returns.append(fill_price / cost - 1)
        return pd.Series(returns, dtype=float)

    @staticmethod
    def _unrealized_pnl(positions: pd.DataFrame) -> float:
        if positions.empty:
            return 0.0
        quantity = pd.to_numeric(positions.get("quantity", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        avg_cost = pd.to_numeric(positions.get("avg_cost", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        last_price = pd.to_numeric(positions.get("last_price", pd.Series(dtype=float)), errors="coerce").fillna(avg_cost)
        return float(((last_price - avg_cost) * quantity).sum())

    @staticmethod
    def _score(
        decision_count: int,
        signal_count: int,
        submitted_count: int,
        rejected_count: int,
        realized_pnl: float,
        unrealized_pnl: float,
        win_rate: float,
    ) -> float:
        data_score = min(decision_count / 100, 1.0) * 20
        activity_score = min(signal_count / 10, 1.0) * 20
        execution_score = 20 if submitted_count == 0 else max(0.0, 1 - rejected_count / max(submitted_count, 1)) * 20
        pnl_score = max(-20.0, min(20.0, (realized_pnl + unrealized_pnl) / 100.0 * 10))
        win_score = win_rate * 20
        return data_score + activity_score + execution_score + pnl_score + win_score

    @staticmethod
    def _status(decision_count: int, buy_fill_count: int, sell_fill_count: int, score: float) -> str:
        if decision_count < 30 or buy_fill_count < 3 or sell_fill_count < 3:
            return "NEEDS_MORE_LIVE_DATA"
        if score >= 70:
            return "LEADING"
        if score >= 50:
            return "OBSERVE"
        return "WEAK"

    def _write_report(self, frame: pd.DataFrame) -> None:
        lines = [
            "# Strategy Scorecard",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "This report attributes local paper trading decisions, orders, fills, and open positions by strategy.",
            "",
        ]
        if frame.empty:
            lines.append("No strategy data is available yet.")
        else:
            columns = [
                "strategy_name",
                "strategy_score",
                "status",
                "decision_count",
                "buy_fill_count",
                "sell_fill_count",
                "open_position_count",
                "realized_pnl",
                "unrealized_pnl",
                "win_rate",
            ]
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in frame.to_dict(orient="records"):
                lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
        (self.output_dir / "strategy_scorecard_report.md").write_text("\n".join(lines), encoding="utf-8")


def _strategy_from_row(row: pd.Series) -> str:
    value = row.get("strategy_name", "")
    if _is_valid_strategy_name(value):
        return str(value).strip()
    reason = str(row.get("reason", "") or row.get("reject_reason", ""))
    if ":" in reason:
        candidate = reason.split(":", 1)[0].strip()
        if candidate:
            return candidate
    if "trend_follow" in reason:
        return "trend_follow"
    if "strict_golden_cross" in reason:
        return "strict_golden_cross"
    return "unattributed"


def _is_valid_strategy_name(value: object) -> bool:
    if pd.isna(value):
        return False
    text = str(value).strip().lower()
    return text not in INVALID_STRATEGY_NAMES


def _open_strategy_by_symbol(trades: pd.DataFrame) -> dict[str, dict[str, object]]:
    open_state: dict[str, dict[str, object]] = {}
    quantities: dict[str, int] = {}
    for _, row in trades.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            continue
        action = str(row.get("action", "")).upper()
        quantity = int(_number(row.get("quantity", 0), 0))
        if quantity <= 0:
            continue
        if action == "BUY":
            quantities[symbol] = quantities.get(symbol, 0) + quantity
            open_state[symbol] = {
                "strategy_name": _strategy_from_row(row),
                "signal_score": _number(row.get("signal_score", 0.0), 0.0),
            }
        elif action == "SELL":
            quantities[symbol] = max(0, quantities.get(symbol, 0) - quantity)
            if quantities[symbol] == 0:
                open_state.pop(symbol, None)
    return open_state


def _number(value: object, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
