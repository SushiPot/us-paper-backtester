from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

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

        account = self._load_or_create_account()
        positions = self._load_positions()
        print(f"[STATUS] virtual_cash={account['virtual_cash']:.2f}", flush=True)
        print(f"[STATUS] 当前虚拟持仓数量={len(positions)}", flush=True)

        market_data = self._load_strategy_data()
        prices = self._latest_prices(market_data)
        equity = self._calculate_equity(account["virtual_cash"], positions, prices)
        account["equity"] = equity
        account["peak_equity"] = max(account["peak_equity"], equity)
        self._save_account(account)
        print(f"[STATUS] 当前虚拟账户权益={equity:.2f}", flush=True)

        if not self._account_risk_ok(account):
            reason = "触发账户风控，停止本次本地模拟盘交易"
            print(f"[EXIT] {reason}", flush=True)
            self._append_run_log("EXIT", reason)
            return

        decisions = self._make_decisions(market_data, account, positions, prices)
        self._append_decision_log(decisions)
        self._save_positions(positions)
        self._save_account(account)
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
        account: dict[str, float],
        positions: dict[str, LocalPosition],
        prices: dict[str, float],
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
            price_check = self._validate_price(symbol, price)
            if not price_check:
                decisions.append(self._reject(symbol, "NONE", "价格为空、为0或NaN"))
                continue

            position = positions.get(symbol)
            buy_met = bool(should_buy(latest))
            sell_reason = self._get_sell_reason(symbol, clean_frame, latest, position, price) if position else ""
            sell_met = bool(sell_reason)
            signal_type = self._signal_type(buy_met, sell_met, position)

            if signal_type == "HOLD":
                decisions.append(LocalDecision(symbol, "HOLD", buy_met, sell_met, True, False, ""))
                continue

            if order_decision_used:
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
                decision = self._execute_buy(symbol, price, account, positions, buy_met, sell_met)
            else:
                decision = self._execute_sell(symbol, price, account, positions, buy_met, sell_met, sell_reason)
            decisions.append(decision)

        return decisions

    def _execute_buy(
        self,
        symbol: str,
        price: float,
        account: dict[str, float],
        positions: dict[str, LocalPosition],
        buy_met: bool,
        sell_met: bool,
    ) -> LocalDecision:
        risk_ok, reject_reason = self._buy_risk_ok(symbol, price, account, positions)
        max_amount = account["equity"] * self.config.max_position_pct
        quantity = int(min(max_amount, account["virtual_cash"]) // price)

        self._append_order_log(symbol, "BUY", quantity, price, "LOCAL_SIMULATED", reject_reason)
        if not risk_ok or quantity <= 0:
            return LocalDecision(symbol, "BUY", buy_met, sell_met, False, False, reject_reason or "数量不足")

        amount = quantity * price
        account["virtual_cash"] -= amount
        positions[symbol] = LocalPosition(symbol, quantity, price, pd.Timestamp.now().normalize())
        self._append_trade_log(symbol, "BUY", quantity, price, amount, account["virtual_cash"])
        print(f"[ORDER] BUY {symbol} qty={quantity} price={price:.2f} amount={amount:.2f}", flush=True)
        return LocalDecision(symbol, "BUY", buy_met, sell_met, True, True, "")

    def _execute_sell(
        self,
        symbol: str,
        price: float,
        account: dict[str, float],
        positions: dict[str, LocalPosition],
        buy_met: bool,
        sell_met: bool,
        reason: str,
    ) -> LocalDecision:
        position = positions.get(symbol)
        if not position:
            self._append_order_log(symbol, "SELL", 0, price, "REJECTED", "没有虚拟持仓，禁止做空")
            return LocalDecision(symbol, "SELL", buy_met, sell_met, False, False, "没有虚拟持仓，禁止做空")

        amount = position.quantity * price
        self._append_order_log(symbol, "SELL", position.quantity, price, "LOCAL_SIMULATED", reason)
        account["virtual_cash"] += amount
        del positions[symbol]
        self._append_trade_log(symbol, "SELL", position.quantity, price, amount, account["virtual_cash"])
        print(f"[ORDER] SELL {symbol} qty={position.quantity} price={price:.2f} amount={amount:.2f}", flush=True)
        return LocalDecision(symbol, "SELL", buy_met, sell_met, True, True, "")

    def _buy_risk_ok(
        self,
        symbol: str,
        price: float,
        account: dict[str, float],
        positions: dict[str, LocalPosition],
    ) -> tuple[bool, str]:
        if symbol in positions:
            return False, "已有持仓，跳过买入"
        if len(positions) >= self.config.max_positions:
            return False, "超过最大同时持仓数量"
        max_amount = account["equity"] * self.config.max_position_pct
        quantity = int(min(max_amount, account["virtual_cash"]) // price)
        if quantity <= 0:
            return False, "虚拟现金不足，无法买入整数股"
        if quantity * price > account["virtual_cash"]:
            return False, "虚拟现金不足，禁止杠杆"
        return True, ""

    def _account_risk_ok(self, account: dict[str, float]) -> bool:
        equity = account["equity"]
        daily_start = account["daily_start_equity"]
        peak = account["peak_equity"]
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

    @staticmethod
    def _validate_price(symbol: str, price: float) -> bool:
        if price is None or not math.isfinite(price) or price <= 0:
            print(f"[WARN] {symbol} 价格异常: {price}", flush=True)
            return False
        return True

    @staticmethod
    def _latest_prices(market_data: dict[str, pd.DataFrame]) -> dict[str, float]:
        prices = {}
        for symbol, frame in market_data.items():
            clean_frame = frame.dropna()
            if not clean_frame.empty:
                prices[symbol] = float(clean_frame.iloc[-1]["close"])
        return prices

    @staticmethod
    def _calculate_equity(
        virtual_cash: float,
        positions: dict[str, LocalPosition],
        prices: dict[str, float],
    ) -> float:
        equity = virtual_cash
        for symbol, position in positions.items():
            equity += position.quantity * prices.get(symbol, position.avg_cost)
        return equity

    def _load_or_create_account(self) -> dict[str, float]:
        path = self.output_dir / self.config.virtual_account_file
        if not path.exists():
            account = {
                "virtual_cash": self.config.initial_cash,
                "equity": self.config.initial_cash,
                "daily_start_equity": self.config.initial_cash,
                "peak_equity": self.config.initial_cash,
            }
            self._save_account(account)
            return account

        row = pd.read_csv(path).iloc[-1]
        return {
            "virtual_cash": float(row["virtual_cash"]),
            "equity": float(row["equity"]),
            "daily_start_equity": float(row["daily_start_equity"]),
            "peak_equity": float(row["peak_equity"]),
        }

    def _save_account(self, account: dict[str, float]) -> None:
        path = self.output_dir / self.config.virtual_account_file
        row = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "virtual_cash": account["virtual_cash"],
                    "equity": account["equity"],
                    "daily_start_equity": account["daily_start_equity"],
                    "peak_equity": account["peak_equity"],
                }
            ]
        )
        row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")

    def _load_positions(self) -> dict[str, LocalPosition]:
        path = self.output_dir / self.config.positions_file
        if not path.exists():
            return {}
        frame = pd.read_csv(path, parse_dates=["entry_date"])
        positions = {}
        for _, row in frame.iterrows():
            positions[str(row["symbol"])] = LocalPosition(
                symbol=str(row["symbol"]),
                quantity=int(row["quantity"]),
                avg_cost=float(row["avg_cost"]),
                entry_date=pd.Timestamp(row["entry_date"]),
            )
        return positions

    def _save_positions(self, positions: dict[str, LocalPosition]) -> None:
        rows = [
            {
                "symbol": position.symbol,
                "quantity": position.quantity,
                "avg_cost": position.avg_cost,
                "entry_date": position.entry_date,
            }
            for position in positions.values()
        ]
        pd.DataFrame(rows, columns=["symbol", "quantity", "avg_cost", "entry_date"]).to_csv(
            self.output_dir / self.config.positions_file,
            index=False,
            encoding="utf-8-sig",
        )

    def _append_order_log(self, symbol: str, action: str, quantity: int, price: float, status: str, reason: str) -> None:
        row = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "symbol": symbol,
                    "action": action,
                    "quantity": quantity,
                    "price": price,
                    "amount": quantity * price,
                    "status": status,
                    "reason": reason,
                }
            ]
        )
        _append_csv(self.output_dir / self.config.paper_order_log_file, row)

    def _append_trade_log(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        amount: float,
        virtual_cash: float,
    ) -> None:
        row = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "symbol": symbol,
                    "action": action,
                    "quantity": quantity,
                    "price": price,
                    "amount": amount,
                    "virtual_cash": virtual_cash,
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

    def _reject(self, symbol: str, signal_type: str, reason: str) -> LocalDecision:
        return LocalDecision(symbol, signal_type, False, False, False, False, reason)

    def _ensure_output_files(self) -> None:
        """即使当天没有订单/成交，也创建标准输出文件表头。"""
        positions_path = self.output_dir / self.config.positions_file
        if not positions_path.exists():
            pd.DataFrame(columns=["symbol", "quantity", "avg_cost", "entry_date"]).to_csv(
                positions_path,
                index=False,
                encoding="utf-8-sig",
            )

        order_path = self.output_dir / self.config.paper_order_log_file
        if not order_path.exists():
            pd.DataFrame(columns=["time", "symbol", "action", "quantity", "price", "amount", "status", "reason"]).to_csv(
                order_path,
                index=False,
                encoding="utf-8-sig",
            )

        trade_path = self.output_dir / self.config.paper_trade_log_file
        if not trade_path.exists():
            pd.DataFrame(
                columns=["time", "symbol", "action", "quantity", "price", "amount", "virtual_cash"]
            ).to_csv(
                trade_path,
                index=False,
                encoding="utf-8-sig",
            )


def _append_csv(path: Path, row: pd.DataFrame) -> None:
    row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
