from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import BacktestConfig, LocalPaperConfig
from .data import MarketDataLoader
from .indicators import add_indicators
from .strategy import should_buy, should_sell_by_signal


@dataclass(frozen=True)
class LocalPosition:
    """本地虚拟持仓。"""

    symbol: str
    quantity: int
    avg_cost: float
    entry_date: pd.Timestamp
    last_price: float = 0.0
    market_value: float = 0.0
    unrealized_return_pct: float = 0.0


@dataclass(frozen=True)
class LocalDecision:
    """本地模拟盘单标的一次决策。"""

    symbol: str
    signal_type: str
    buy_condition_met: bool
    sell_condition_met: bool
    risk_passed: bool
    order_submitted: bool
    reject_reason: str


@dataclass(frozen=True)
class Fill:
    """本地虚拟成交回报。"""

    symbol: str
    action: str
    quantity: int
    signal_price: float
    fill_price: float
    gross_amount: float
    commission: float
    net_cash_change: float
    reason: str


class LocalPaperTrader:
    """不连接券商的本地模拟盘。每天运行一次即可。"""

    def __init__(self, config: LocalPaperConfig) -> None:
        self.config = config
        self.output_dir = config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> None:
        print("[START] LocalPaperTrader.run_once 已进入", flush=True)
        self._ensure_output_files()
        self._append_run_log("START", "本地模拟盘一次性运行开始")

        market_data = self._load_strategy_data()
        market_date = self._latest_market_date(market_data)
        prices = self._latest_prices(market_data)
        previous_prices = self._previous_prices(market_data)

        account = self._load_or_create_account(market_date)
        positions = self._mark_positions_to_market(self._load_positions(), prices)
        equity = self._calculate_equity(account["virtual_cash"], positions)
        account["equity"] = equity
        account["peak_equity"] = max(account["peak_equity"], equity)

        print(f"[STATUS] market_date={market_date.date()}", flush=True)
        print(f"[STATUS] virtual_cash={account['virtual_cash']:.2f}", flush=True)
        print(f"[STATUS] 当前虚拟持仓数量={len(positions)}", flush=True)
        print(f"[STATUS] 当前虚拟账户权益={equity:.2f}", flush=True)

        if not self._account_risk_ok(account):
            reason = "触发账户风控，停止本次本地模拟盘交易"
            print(f"[EXIT] {reason}", flush=True)
            self._append_run_log("EXIT", reason)
            self._save_positions(positions)
            self._save_account(account)
            self._append_account_history(account, market_date)
            self._write_report(account, positions)
            return

        decisions = self._make_decisions(market_data, account, positions, prices, previous_prices, market_date)
        positions = self._mark_positions_to_market(positions, prices)
        account["equity"] = self._calculate_equity(account["virtual_cash"], positions)
        account["peak_equity"] = max(account["peak_equity"], account["equity"])

        self._append_decision_log(decisions)
        self._save_positions(positions)
        self._save_account(account)
        self._append_account_history(account, market_date)
        self._write_report(account, positions)
        self._append_run_log("END", f"本地模拟盘一次性运行完成，决策数={len(decisions)}")
        print("[END] LocalPaperTrader.run_once 正常结束", flush=True)

    def _load_strategy_data(self) -> dict[str, pd.DataFrame]:
        print("[CHECK] 加载 yfinance / Yahoo 历史行情", flush=True)
        data_config = BacktestConfig(
            symbols=self.config.symbols,
            start_date=self.config.historical_start_date,
            output_dir=self.config.output_dir,
            retry_count=self.config.retry_count,
            retry_wait_seconds=self.config.retry_wait_seconds,
        )
        raw_data = MarketDataLoader(data_config).download_all()
        data = {symbol: add_indicators(frame) for symbol, frame in raw_data.items()}
        print("[OK] 历史行情和指标加载完成", flush=True)
        return data

    def _make_decisions(
        self,
        market_data: dict[str, pd.DataFrame],
        account: dict[str, float | str],
        positions: dict[str, LocalPosition],
        prices: dict[str, float],
        previous_prices: dict[str, float],
        market_date: pd.Timestamp,
    ) -> list[LocalDecision]:
        decisions: list[LocalDecision] = []
        order_decision_used = False

        for symbol in self.config.symbols:
            print(f"[CHECK] 生成 {symbol} 本地模拟盘决策", flush=True)
            frame = market_data.get(symbol)
            if frame is None or frame.empty:
                decisions.append(self._reject(symbol, "NONE", "行情数据为空"))
                continue

            clean_frame = frame.dropna()
            if clean_frame.empty:
                decisions.append(self._reject(symbol, "NONE", "指标数据为空"))
                continue

            latest = clean_frame.iloc[-1]
            price = prices.get(symbol, 0.0)
            previous_price = previous_prices.get(symbol, 0.0)
            price_ok, price_reason = self._validate_price(symbol, price, previous_price)
            if not price_ok:
                decisions.append(self._reject(symbol, "NONE", price_reason))
                continue

            position = positions.get(symbol)
            buy_met = bool(should_buy(latest))
            sell_reason = self._get_sell_reason(symbol, clean_frame, latest, position, price) if position else ""
            sell_met = bool(sell_reason)
            signal_type = self._signal_type(buy_met, sell_met, position)

            if signal_type == "HOLD":
                decisions.append(LocalDecision(symbol, "HOLD", buy_met, sell_met, True, False, ""))
                continue

            if self.config.allow_one_order_per_run and order_decision_used:
                decisions.append(
                    LocalDecision(
                        symbol,
                        signal_type,
                        buy_met,
                        sell_met,
                        False,
                        False,
                        "本次运行已生成过一次订单决策",
                    )
                )
                continue

            order_decision_used = True
            if signal_type == "BUY":
                decision = self._execute_buy(symbol, price, account, positions, buy_met, sell_met, market_date)
            else:
                decision = self._execute_sell(symbol, price, account, positions, buy_met, sell_met, sell_reason)
            decisions.append(decision)

        return decisions

    def _execute_buy(
        self,
        symbol: str,
        price: float,
        account: dict[str, float | str],
        positions: dict[str, LocalPosition],
        buy_met: bool,
        sell_met: bool,
        market_date: pd.Timestamp,
    ) -> LocalDecision:
        risk_ok, reject_reason, quantity = self._buy_risk_ok(symbol, price, account, positions)
        self._append_order_log(symbol, "BUY", quantity, price, "REJECTED" if not risk_ok else "LOCAL_SIMULATED", reject_reason)
        if not risk_ok:
            return LocalDecision(symbol, "BUY", buy_met, sell_met, False, False, reject_reason)

        fill = self._simulate_fill(symbol, "BUY", quantity, price, "MA20上穿MA60且RSI<70且放量")
        if fill.net_cash_change > float(account["virtual_cash"]):
            reason = "含滑点和手续费后虚拟现金不足，禁止杠杆"
            self._append_order_log(symbol, "BUY", quantity, price, "REJECTED", reason)
            return LocalDecision(symbol, "BUY", buy_met, sell_met, False, False, reason)

        account["virtual_cash"] = float(account["virtual_cash"]) - fill.net_cash_change
        positions[symbol] = LocalPosition(
            symbol=symbol,
            quantity=quantity,
            avg_cost=fill.fill_price,
            entry_date=market_date.normalize(),
            last_price=price,
            market_value=quantity * price,
            unrealized_return_pct=price / fill.fill_price - 1,
        )
        self._append_trade_log(fill, float(account["virtual_cash"]))
        print(
            f"[ORDER] BUY {symbol} qty={quantity} signal={price:.2f} fill={fill.fill_price:.2f} "
            f"commission={fill.commission:.2f}",
            flush=True,
        )
        return LocalDecision(symbol, "BUY", buy_met, sell_met, True, True, "")

    def _execute_sell(
        self,
        symbol: str,
        price: float,
        account: dict[str, float | str],
        positions: dict[str, LocalPosition],
        buy_met: bool,
        sell_met: bool,
        reason: str,
    ) -> LocalDecision:
        position = positions.get(symbol)
        if not position:
            self._append_order_log(symbol, "SELL", 0, price, "REJECTED", "没有虚拟持仓，禁止做空")
            return LocalDecision(symbol, "SELL", buy_met, sell_met, False, False, "没有虚拟持仓，禁止做空")

        fill = self._simulate_fill(symbol, "SELL", position.quantity, price, reason)
        self._append_order_log(symbol, "SELL", position.quantity, price, "LOCAL_SIMULATED", reason)
        account["virtual_cash"] = float(account["virtual_cash"]) + fill.net_cash_change
        del positions[symbol]
        self._append_trade_log(fill, float(account["virtual_cash"]))
        print(
            f"[ORDER] SELL {symbol} qty={position.quantity} signal={price:.2f} fill={fill.fill_price:.2f} "
            f"commission={fill.commission:.2f}",
            flush=True,
        )
        return LocalDecision(symbol, "SELL", buy_met, sell_met, True, True, "")

    def _simulate_fill(self, symbol: str, action: str, quantity: int, signal_price: float, reason: str) -> Fill:
        slippage_multiplier = 1 + self.config.slippage_pct if action == "BUY" else 1 - self.config.slippage_pct
        fill_price = signal_price * slippage_multiplier
        gross_amount = quantity * fill_price
        commission = max(quantity * self.config.commission_per_share, self.config.min_commission)
        net_cash_change = gross_amount + commission if action == "BUY" else gross_amount - commission
        return Fill(
            symbol=symbol,
            action=action,
            quantity=quantity,
            signal_price=signal_price,
            fill_price=fill_price,
            gross_amount=gross_amount,
            commission=commission,
            net_cash_change=net_cash_change,
            reason=reason,
        )

    def _buy_risk_ok(
        self,
        symbol: str,
        price: float,
        account: dict[str, float | str],
        positions: dict[str, LocalPosition],
    ) -> tuple[bool, str, int]:
        if symbol in positions:
            return False, "已有持仓，跳过买入", 0
        if len(positions) >= self.config.max_positions:
            return False, "超过最大同时持仓数量", 0

        max_amount = float(account["equity"]) * self.config.max_position_pct
        quantity = int(min(max_amount, float(account["virtual_cash"])) // (price * (1 + self.config.slippage_pct)))
        if quantity <= 0:
            return False, "虚拟现金不足，无法买入整数股", 0

        estimated_fill = self._simulate_fill(symbol, "BUY", quantity, price, "风险预估")
        if estimated_fill.net_cash_change > float(account["virtual_cash"]):
            return False, "含滑点和手续费后虚拟现金不足，禁止杠杆", quantity
        if estimated_fill.net_cash_change > max_amount + self.config.min_commission:
            return False, "超过单笔 20% 仓位限制", quantity
        return True, "", quantity

    def _account_risk_ok(self, account: dict[str, float | str]) -> bool:
        equity = float(account["equity"])
        daily_start = float(account["daily_start_equity"])
        peak = float(account["peak_equity"])
        if daily_start > 0 and equity / daily_start - 1 <= self.config.daily_loss_limit_pct:
            return False
        if peak > 0 and equity / peak - 1 <= self.config.max_account_drawdown_pct:
            return False
        return True

    def _get_sell_reason(
        self,
        symbol: str,
        frame: pd.DataFrame,
        latest: pd.Series,
        position: LocalPosition | None,
        price: float,
    ) -> str:
        if not position:
            return ""
        return_pct = price / position.avg_cost - 1
        if should_sell_by_signal(latest):
            return "MA20下穿MA60"
        if return_pct <= self.config.stop_loss_pct:
            return "止损"
        if return_pct >= self.config.take_profit_pct:
            return "止盈"
        holding_days = int(((frame.index > position.entry_date) & (frame.index <= frame.index[-1])).sum())
        if holding_days > self.config.max_holding_days:
            return "持仓超过30个交易日"
        return ""

    @staticmethod
    def _signal_type(buy_met: bool, sell_met: bool, position: LocalPosition | None) -> str:
        if position and sell_met:
            return "SELL"
        if not position and buy_met:
            return "BUY"
        return "HOLD"

    def _validate_price(self, symbol: str, price: float, previous_price: float) -> tuple[bool, str]:
        if price is None or not math.isfinite(price) or price <= 0:
            reason = "价格为空、为0或NaN"
            print(f"[WARN] {symbol} {reason}: {price}", flush=True)
            return False, reason
        if previous_price and math.isfinite(previous_price) and previous_price > 0:
            change = abs(price / previous_price - 1)
            if change > self.config.max_price_change_pct:
                reason = f"价格相对前一交易日波动超过30%: {change:.2%}"
                print(f"[WARN] {symbol} {reason}", flush=True)
                return False, reason
        return True, ""

    @staticmethod
    def _latest_prices(market_data: dict[str, pd.DataFrame]) -> dict[str, float]:
        prices = {}
        for symbol, frame in market_data.items():
            clean_frame = frame.dropna()
            if not clean_frame.empty:
                prices[symbol] = float(clean_frame.iloc[-1]["close"])
        return prices

    @staticmethod
    def _previous_prices(market_data: dict[str, pd.DataFrame]) -> dict[str, float]:
        prices = {}
        for symbol, frame in market_data.items():
            clean_frame = frame.dropna()
            if len(clean_frame) >= 2:
                prices[symbol] = float(clean_frame.iloc[-2]["close"])
        return prices

    @staticmethod
    def _latest_market_date(market_data: dict[str, pd.DataFrame]) -> pd.Timestamp:
        dates = [frame.dropna().index[-1] for frame in market_data.values() if not frame.dropna().empty]
        if not dates:
            raise RuntimeError("没有可用行情日期")
        return pd.Timestamp(max(dates))

    @staticmethod
    def _calculate_equity(virtual_cash: float | str, positions: dict[str, LocalPosition]) -> float:
        equity = float(virtual_cash)
        for position in positions.values():
            equity += position.market_value
        return equity

    @staticmethod
    def _mark_positions_to_market(
        positions: dict[str, LocalPosition],
        prices: dict[str, float],
    ) -> dict[str, LocalPosition]:
        marked = {}
        for symbol, position in positions.items():
            last_price = prices.get(symbol, position.last_price or position.avg_cost)
            market_value = position.quantity * last_price
            marked[symbol] = LocalPosition(
                symbol=position.symbol,
                quantity=position.quantity,
                avg_cost=position.avg_cost,
                entry_date=position.entry_date,
                last_price=last_price,
                market_value=market_value,
                unrealized_return_pct=last_price / position.avg_cost - 1,
            )
        return marked

    def _load_or_create_account(self, market_date: pd.Timestamp) -> dict[str, float | str]:
        path = self.output_dir / self.config.virtual_account_file
        if not path.exists() or path.stat().st_size == 0:
            return {
                "as_of_date": market_date.date().isoformat(),
                "virtual_cash": self.config.initial_cash,
                "equity": self.config.initial_cash,
                "daily_start_equity": self.config.initial_cash,
                "peak_equity": self.config.initial_cash,
            }

        row = pd.read_csv(path).iloc[-1]
        account = {
            "as_of_date": str(row.get("as_of_date", market_date.date().isoformat())),
            "virtual_cash": float(row["virtual_cash"]),
            "equity": float(row["equity"]),
            "daily_start_equity": float(row["daily_start_equity"]),
            "peak_equity": float(row["peak_equity"]),
        }

        if account["as_of_date"] != market_date.date().isoformat():
            account["as_of_date"] = market_date.date().isoformat()
            account["daily_start_equity"] = float(account["equity"])
        return account

    def _save_account(self, account: dict[str, float | str]) -> None:
        path = self.output_dir / self.config.virtual_account_file
        row = pd.DataFrame(
            [
                {
                    "as_of_date": account["as_of_date"],
                    "virtual_cash": account["virtual_cash"],
                    "equity": account["equity"],
                    "daily_start_equity": account["daily_start_equity"],
                    "peak_equity": account["peak_equity"],
                }
            ]
        )
        row.to_csv(path, index=False, encoding="utf-8-sig")

    def _append_account_history(self, account: dict[str, float | str], market_date: pd.Timestamp) -> None:
        row = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "market_date": market_date.date().isoformat(),
                    "virtual_cash": account["virtual_cash"],
                    "equity": account["equity"],
                    "daily_start_equity": account["daily_start_equity"],
                    "peak_equity": account["peak_equity"],
                }
            ]
        )
        _append_csv(self.output_dir / self.config.account_history_file, row)

    def _load_positions(self) -> dict[str, LocalPosition]:
        path = self.output_dir / self.config.positions_file
        if not path.exists() or path.stat().st_size == 0:
            return {}
        frame = pd.read_csv(path, parse_dates=["entry_date"])
        positions = {}
        for _, row in frame.iterrows():
            if pd.isna(row.get("symbol")):
                continue
            positions[str(row["symbol"])] = LocalPosition(
                symbol=str(row["symbol"]),
                quantity=int(row["quantity"]),
                avg_cost=float(row["avg_cost"]),
                entry_date=pd.Timestamp(row["entry_date"]),
                last_price=float(row.get("last_price", row["avg_cost"])),
                market_value=float(row.get("market_value", int(row["quantity"]) * float(row["avg_cost"]))),
                unrealized_return_pct=float(row.get("unrealized_return_pct", 0.0)),
            )
        return positions

    def _save_positions(self, positions: dict[str, LocalPosition]) -> None:
        rows = [
            {
                "symbol": position.symbol,
                "quantity": position.quantity,
                "avg_cost": position.avg_cost,
                "entry_date": position.entry_date,
                "last_price": position.last_price,
                "market_value": position.market_value,
                "unrealized_return_pct": position.unrealized_return_pct,
            }
            for position in positions.values()
        ]
        pd.DataFrame(
            rows,
            columns=[
                "symbol",
                "quantity",
                "avg_cost",
                "entry_date",
                "last_price",
                "market_value",
                "unrealized_return_pct",
            ],
        ).to_csv(self.output_dir / self.config.positions_file, index=False, encoding="utf-8-sig")

    def _append_order_log(self, symbol: str, action: str, quantity: int, price: float, status: str, reason: str) -> None:
        next_id = self._next_sequence_id(self.output_dir / self.config.paper_order_log_file, "order_id")
        row = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "order_id": next_id,
                    "symbol": symbol,
                    "action": action,
                    "quantity": quantity,
                    "signal_price": price,
                    "estimated_amount": quantity * price,
                    "status": status,
                    "reason": reason,
                }
            ]
        )
        _append_csv(self.output_dir / self.config.paper_order_log_file, row)

    def _append_trade_log(self, fill: Fill, virtual_cash: float) -> None:
        next_id = self._next_sequence_id(self.output_dir / self.config.paper_trade_log_file, "trade_id")
        row = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "trade_id": next_id,
                    "symbol": fill.symbol,
                    "action": fill.action,
                    "quantity": fill.quantity,
                    "signal_price": fill.signal_price,
                    "fill_price": fill.fill_price,
                    "gross_amount": fill.gross_amount,
                    "commission": fill.commission,
                    "net_cash_change": fill.net_cash_change,
                    "virtual_cash": virtual_cash,
                    "reason": fill.reason,
                }
            ]
        )
        _append_csv(self.output_dir / self.config.paper_trade_log_file, row)

    def _append_decision_log(self, decisions: list[LocalDecision]) -> None:
        rows = [
            {
                "time": pd.Timestamp.now(),
                "symbol": decision.symbol,
                "signal_type": decision.signal_type,
                "buy_condition_met": decision.buy_condition_met,
                "sell_condition_met": decision.sell_condition_met,
                "risk_passed": decision.risk_passed,
                "order_submitted": decision.order_submitted,
                "reject_reason": decision.reject_reason,
            }
            for decision in decisions
        ]
        _append_csv(self.output_dir / self.config.decision_log_file, pd.DataFrame(rows))

    def _append_run_log(self, event_type: str, message: str) -> None:
        row = pd.DataFrame([{"time": pd.Timestamp.now(), "event_type": event_type, "message": message}])
        _append_csv(self.output_dir / self.config.run_log_file, row)

    def _write_report(self, account: dict[str, float | str], positions: dict[str, LocalPosition]) -> None:
        history_path = self.output_dir / self.config.account_history_file
        report = {
            "as_of_date": account["as_of_date"],
            "virtual_cash": account["virtual_cash"],
            "equity": account["equity"],
            "total_return": float(account["equity"]) / self.config.initial_cash - 1,
            "open_positions": len(positions),
            "gross_exposure": sum(position.market_value for position in positions.values()),
            "cash_pct": float(account["virtual_cash"]) / float(account["equity"]) if float(account["equity"]) else 0.0,
        }

        if history_path.exists() and history_path.stat().st_size > 0:
            history = pd.read_csv(history_path, parse_dates=["time"])
            equity = history["equity"].astype(float)
            returns = equity.pct_change().dropna()
            drawdown = equity / equity.cummax() - 1
            report["max_drawdown"] = float(drawdown.min()) if not drawdown.empty else 0.0
            report["sharpe_ratio"] = float((returns.mean() / returns.std(ddof=0)) * np.sqrt(252)) if returns.std(ddof=0) > 0 else 0.0
            self._plot_local_equity_curve(history)
        else:
            report["max_drawdown"] = 0.0
            report["sharpe_ratio"] = 0.0

        pd.DataFrame([report]).to_csv(
            self.output_dir / self.config.local_report_file,
            index=False,
            encoding="utf-8-sig",
        )

    def _plot_local_equity_curve(self, history: pd.DataFrame) -> None:
        if history.empty:
            return
        plt.figure(figsize=(12, 6))
        plt.plot(pd.to_datetime(history["time"]), history["equity"], label="Local Paper Equity")
        plt.title("Local Paper Equity Curve")
        plt.xlabel("Time")
        plt.ylabel("Equity")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(self.output_dir / self.config.local_equity_curve_file, dpi=150)
        plt.close()

    def _reject(self, symbol: str, signal_type: str, reason: str) -> LocalDecision:
        return LocalDecision(symbol, signal_type, False, False, False, False, reason)

    def _ensure_output_files(self) -> None:
        """即使当天没有订单/成交，也创建标准输出文件表头。"""
        files = {
            self.config.positions_file: [
                "symbol",
                "quantity",
                "avg_cost",
                "entry_date",
                "last_price",
                "market_value",
                "unrealized_return_pct",
            ],
            self.config.virtual_account_file: [
                "as_of_date",
                "virtual_cash",
                "equity",
                "daily_start_equity",
                "peak_equity",
            ],
            self.config.account_history_file: [
                "time",
                "market_date",
                "virtual_cash",
                "equity",
                "daily_start_equity",
                "peak_equity",
            ],
            self.config.paper_order_log_file: [
                "time",
                "order_id",
                "symbol",
                "action",
                "quantity",
                "signal_price",
                "estimated_amount",
                "status",
                "reason",
            ],
            self.config.paper_trade_log_file: [
                "time",
                "trade_id",
                "symbol",
                "action",
                "quantity",
                "signal_price",
                "fill_price",
                "gross_amount",
                "commission",
                "net_cash_change",
                "virtual_cash",
                "reason",
            ],
        }

        for filename, columns in files.items():
            path = self.output_dir / filename
            self._ensure_csv_schema(path, columns)

    @staticmethod
    def _next_sequence_id(path: Path, column: str) -> int:
        if not path.exists() or path.stat().st_size == 0:
            return 1
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return 1
        if frame.empty or column not in frame.columns:
            return 1
        return int(frame[column].max()) + 1

    @staticmethod
    def _ensure_csv_schema(path: Path, columns: list[str]) -> None:
        if not path.exists() or path.stat().st_size == 0:
            pd.DataFrame(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")
            return

        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            pd.DataFrame(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")
            return

        missing = [column for column in columns if column not in frame.columns]
        extra = [column for column in frame.columns if column not in columns]
        if missing or extra:
            for column in missing:
                frame[column] = pd.NA
            frame = frame.reindex(columns=columns)
            frame.to_csv(path, index=False, encoding="utf-8-sig")


def _append_csv(path: Path, row: pd.DataFrame) -> None:
    row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
