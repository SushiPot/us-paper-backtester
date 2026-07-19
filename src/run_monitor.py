from __future__ import annotations

import math
import traceback
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import PaperTradingConfig, build_market_data_config
from .data import MarketDataLoader
from .ibkr_client import AccountSnapshot, IBKRClient, PositionSnapshot
from .indicators import add_indicators
from .live_risk import LiveRiskManager, PositionStateStore
from .order_manager import OrderIntent, OrderManager, OrderSubmitResult
from .safety_check import (
    append_safety_log,
    build_startup_snapshot,
    print_startup_confirmation,
    validate_startup,
)
from .strategy import should_buy, should_sell_by_signal


@dataclass(frozen=True)
class SymbolDecision:
    """单只股票的一次决策结果。"""

    symbol: str
    signal_type: str
    buy_condition_met: bool
    sell_condition_met: bool
    risk_passed: bool
    dry_run: bool
    sent_to_paper: bool
    reject_reason: str


class RunMonitor:
    """第三阶段：一次运行、一次扫描、一次决策日志，不做循环交易。"""

    def __init__(self, config: PaperTradingConfig, assume_yes: bool = False) -> None:
        self.config = config
        self.assume_yes = assume_yes
        self.client = IBKRClient(config)
        self.risk = LiveRiskManager(config)
        self.order_manager = OrderManager(config, self.client, self.risk)
        self.position_state = PositionStateStore(config.output_dir, config.paper_position_state_file)
        self.output_dir = config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> None:
        self._status("[START] RunMonitor.run_once 已进入")
        self._append_run_log("START", "启动一次性监控运行")
        try:
            self._status("[CHECK] 准备连接 IBKR")
            self.client.connect(require_paper=False)
            self._status("[OK] IBKR 连接成功")

            self._status("[CHECK] 准备读取账户资金")
            account = self.client.get_account_snapshot(require_paper=False)
            self._status(
                f"[OK] 账户资金读取成功: account={account.account}, "
                f"cash={account.cash:.2f}, available={account.available_funds:.2f}, "
                f"net_liquidation={account.net_liquidation:.2f}"
            )

            self._status("[CHECK] 准备读取当前持仓")
            positions = self.client.get_positions(require_paper=False)
            self._status(f"[OK] 当前持仓读取成功: positions={len(positions)}")

            self._status("[CHECK] 准备构建运行前确认信息")
            snapshot = build_startup_snapshot(self.config, account, positions)
            self._status("[OK] 运行前确认信息构建完成")
            print_startup_confirmation(snapshot)

            self._status("[CHECK] 准备执行启动安全检查")
            safety = validate_startup(self.config, snapshot)
            self._status(f"[RESULT] 启动安全检查: allowed={safety.allowed}, reason={safety.reason}")
            append_safety_log(self.output_dir, self.config.safety_log_file, "STARTUP_CHECK", safety.reason)
            if not safety.allowed:
                self._status(f"[EXIT] {safety.reason}")
                self._append_run_log("EXIT", safety.reason)
                return

            self._status("[CHECK] 准备执行人工确认")
            if not self._confirm_start():
                self._status("[EXIT] 用户取消运行")
                self._append_run_log("EXIT", "用户取消运行")
                return
            self._status("[OK] 人工确认通过")

            self._status("[CHECK] 准备执行账户风控检查")
            account_risk = self.risk.update_account_risk(account)
            self._status(f"[RESULT] 账户风控检查: allowed={account_risk.allowed}, reason={account_risk.reason}")
            if not account_risk.allowed:
                append_safety_log(self.output_dir, self.config.safety_log_file, "RISK_STOP", account_risk.reason)
                self._status(f"[EXIT] {account_risk.reason}")
                self._append_run_log("EXIT", account_risk.reason)
                return

            self._status("[CHECK] 准备加载策略历史数据")
            market_data = self._load_strategy_data()
            self._status(f"[OK] 策略历史数据加载完成: symbols={list(market_data.keys())}")

            self._status("[CHECK] 准备生成一次性订单决策")
            decisions = self._make_single_scan_decisions(market_data, account, positions)
            self._status(f"[OK] 一次性订单决策生成完成: decisions={len(decisions)}")

            self._status("[CHECK] 准备写入 decision_log.csv")
            self._append_decision_log(decisions)
            self._status("[OK] decision_log.csv 写入完成")
            self._append_run_log("END", f"一次性监控运行完成，决策数: {len(decisions)}")
            self._status("[END] RunMonitor.run_once 正常结束")
        except Exception as exc:
            message = f"出现异常或网络中断，自动停止交易且不重连下单: {exc}"
            self._status(f"[ERROR] {message}")
            traceback.print_exc()
            append_safety_log(self.output_dir, self.config.safety_log_file, "EXCEPTION", message)
            self._append_run_log("ERROR", message)
            raise
        finally:
            self._status("[CHECK] 准备断开 IBKR 连接")
            self.client.disconnect()
            self._status("[OK] IBKR 连接已断开")

    def _confirm_start(self) -> bool:
        if self.assume_yes:
            self._status("已通过 --yes 跳过人工确认，仅用于你明确要求的手动运行场景。")
            return True
        answer = input("确认只运行一次并生成一次订单决策？输入 YES 继续: ").strip()
        self._status(f"[RESULT] 人工确认输入: {answer!r}")
        return answer == "YES"

    def _load_strategy_data(self) -> dict[str, pd.DataFrame]:
        self._status("[CHECK] 创建 BacktestConfig 用于历史数据")
        data_config = build_market_data_config(self.config)
        self._status("[CHECK] 开始下载/读取历史数据")
        raw_data = MarketDataLoader(data_config).download_all()
        self._status("[OK] 历史数据下载/读取完成，开始计算指标")
        return {symbol: add_indicators(frame) for symbol, frame in raw_data.items()}

    def _make_single_scan_decisions(
        self,
        market_data: dict[str, pd.DataFrame],
        account: AccountSnapshot,
        positions: dict[str, PositionSnapshot],
    ) -> list[SymbolDecision]:
        decisions: list[SymbolDecision] = []
        order_decision_used = False

        for symbol in self.config.symbols:
            self._status(f"[CHECK] 开始检查 {symbol}")
            if not self.client.ib.isConnected():
                self._status(f"[RESULT] {symbol}: IBKR 连接已断开")
                decisions.append(self._reject(symbol, "NONE", "网络连接已断开，停止生成订单"))
                break

            frame = market_data.get(symbol)
            if frame is None or frame.empty:
                self._status(f"[RESULT] {symbol}: 行情数据为空，禁止下单")
                decisions.append(self._reject(symbol, "NONE", "行情数据为空，禁止下单"))
                continue

            clean_frame = frame.dropna()
            if clean_frame.empty:
                self._status(f"[RESULT] {symbol}: 指标数据为空，禁止下单")
                decisions.append(self._reject(symbol, "NONE", "指标数据为空，禁止下单"))
                continue

            latest = clean_frame.iloc[-1]
            historical_close = float(latest["close"])
            self._status(f"[OK] {symbol}: 最新历史收盘价={historical_close:.2f}")
            buy_met = bool(should_buy(latest))
            position = positions.get(symbol)
            sell_reason = ""
            if position:
                sell_reason = self._get_sell_reason(symbol, clean_frame, latest, position, historical_close)
            sell_met = bool(sell_reason)
            self._status(
                f"[RESULT] {symbol}: buy_met={buy_met}, sell_met={sell_met}, "
                f"position={'YES' if position else 'NO'}"
            )

            signal_type = self._signal_type(buy_met, sell_met, position)
            if signal_type == "HOLD":
                self._status(f"[RESULT] {symbol}: HOLD，无订单决策")
                decisions.append(
                    SymbolDecision(symbol, signal_type, buy_met, sell_met, True, self.config.dry_run, False, "")
                )
                continue

            if order_decision_used:
                self._status(f"[RESULT] {symbol}: 本次运行已使用唯一订单决策额度")
                decisions.append(
                    SymbolDecision(
                        symbol,
                        signal_type,
                        buy_met,
                        sell_met,
                        False,
                        self.config.dry_run,
                        False,
                        "本次运行已生成过一次订单决策，禁止继续下单",
                    )
                )
                continue

            order_decision_used = True
            self._status(f"[CHECK] {symbol}: 准备读取实时/延迟行情")
            price_result = self._safe_market_price(symbol, historical_close)
            self._status(
                f"[RESULT] {symbol}: price_allowed={price_result.allowed}, "
                f"price={price_result.price:.2f}, reason={price_result.reason}"
            )
            if not price_result.allowed:
                decisions.append(
                    SymbolDecision(
                        symbol,
                        signal_type,
                        buy_met,
                        sell_met,
                        False,
                        self.config.dry_run,
                        False,
                        price_result.reason,
                    )
                )
                if not self.client.ib.isConnected():
                    break
                continue

            self._status(f"[CHECK] {symbol}: 准备生成订单意图")
            intent = self._build_order_intent(symbol, signal_type, price_result.price, account, position, sell_reason)
            if intent is None:
                self._status(f"[RESULT] {symbol}: 无法生成有效订单数量")
                decisions.append(
                    SymbolDecision(
                        symbol,
                        signal_type,
                        buy_met,
                        sell_met,
                        False,
                        self.config.dry_run,
                        False,
                        "无法生成有效订单数量",
                    )
                )
                continue

            self._status(f"[CHECK] {symbol}: 准备提交到订单管理器，DRY_RUN={self.config.dry_run}")
            submit_result = self.order_manager.submit(intent, account, positions)
            self._status(
                f"[RESULT] {symbol}: risk_passed={submit_result.risk_passed}, "
                f"sent_to_paper={submit_result.sent_to_paper}, status={submit_result.status}, "
                f"reject_reason={submit_result.reject_reason}"
            )
            decisions.append(
                SymbolDecision(
                    symbol=symbol,
                    signal_type=signal_type,
                    buy_condition_met=buy_met,
                    sell_condition_met=sell_met,
                    risk_passed=submit_result.risk_passed,
                    dry_run=self.config.dry_run,
                    sent_to_paper=submit_result.sent_to_paper,
                    reject_reason=submit_result.reject_reason,
                )
            )

        return decisions

    def _safe_market_price(self, symbol: str, historical_close: float):
        try:
            price = self.client.get_market_price(symbol)
        except Exception as exc:
            self._status(f"[ERROR] {symbol}: 行情读取异常: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            return _PriceCheck(False, 0.0, f"行情读取失败，禁止下单: {exc}")

        if price is None or not math.isfinite(price) or price <= 0:
            self._status(f"[RESULT] {symbol}: 价格异常 price={price}")
            return _PriceCheck(False, 0.0, "价格为空、NaN 或小于等于 0，禁止下单")
        if historical_close <= 0 or not math.isfinite(historical_close):
            self._status(f"[RESULT] {symbol}: 历史收盘价异常 historical_close={historical_close}")
            return _PriceCheck(False, 0.0, "历史收盘价异常，禁止下单")

        change = abs(price / historical_close - 1)
        if change > self.config.max_price_change_pct:
            self._status(f"[RESULT] {symbol}: 价格波动异常 change={change:.2%}")
            return _PriceCheck(False, price, f"实时价格相对最新历史收盘价波动超过30%: {change:.2%}")
        return _PriceCheck(True, price, "")

    def _build_order_intent(
        self,
        symbol: str,
        signal_type: str,
        price: float,
        account: AccountSnapshot,
        position: PositionSnapshot | None,
        sell_reason: str,
    ) -> OrderIntent | None:
        if signal_type == "BUY":
            max_position_pct = self.config.special_max_position_pct.get(symbol, self.config.max_position_pct)
            max_amount = account.net_liquidation * max_position_pct
            quantity = int(min(max_amount, account.available_funds) // price)
            if quantity <= 0:
                return None
            return OrderIntent(symbol, "BUY", quantity, price, "MA20上穿MA60且RSI<70且放量")
        if signal_type == "SELL" and position:
            return OrderIntent(symbol, "SELL", position.quantity, price, sell_reason)
        return None

    def _get_sell_reason(
        self,
        symbol: str,
        frame: pd.DataFrame,
        latest: pd.Series,
        position: PositionSnapshot,
        market_price: float,
    ) -> str:
        return_pct = market_price / position.avg_cost - 1
        if should_sell_by_signal(latest):
            return "MA20下穿MA60"
        if return_pct <= self.config.stop_loss_pct:
            return "止损"
        if return_pct >= self.config.take_profit_pct:
            return "止盈"
        entry_date = self.position_state.get_entry_date(symbol)
        if entry_date is not None:
            holding_days = int(((frame.index > entry_date) & (frame.index <= frame.index[-1])).sum())
            if holding_days > self.config.max_holding_days:
                return "持仓超过30个交易日"
        return ""

    @staticmethod
    def _signal_type(buy_met: bool, sell_met: bool, position: PositionSnapshot | None) -> str:
        if position and sell_met:
            return "SELL"
        if not position and buy_met:
            return "BUY"
        return "HOLD"

    def _reject(self, symbol: str, signal_type: str, reason: str) -> SymbolDecision:
        return SymbolDecision(symbol, signal_type, False, False, False, self.config.dry_run, False, reason)

    def _append_decision_log(self, decisions: list[SymbolDecision]) -> None:
        rows = [
            {
                "时间": pd.Timestamp.now(),
                "股票代码": decision.symbol,
                "信号类型": decision.signal_type,
                "是否满足买入条件": decision.buy_condition_met,
                "是否满足卖出条件": decision.sell_condition_met,
                "是否通过风控": decision.risk_passed,
                "是否 dry_run": decision.dry_run,
                "是否实际发送到 Paper": decision.sent_to_paper,
                "拒绝原因": decision.reject_reason,
            }
            for decision in decisions
        ]
        _append_csv(self.output_dir / self.config.decision_log_file, pd.DataFrame(rows))

    def _append_run_log(self, event_type: str, message: str) -> None:
        row = pd.DataFrame([{"时间": pd.Timestamp.now(), "事件类型": event_type, "内容": message}])
        _append_csv(self.output_dir / self.config.run_log_file, row)

    @staticmethod
    def _status(message: str) -> None:
        print(message, flush=True)


@dataclass(frozen=True)
class _PriceCheck:
    allowed: bool
    price: float
    reason: str


def _append_csv(path: Path, row: pd.DataFrame) -> None:
    row.to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8-sig")
