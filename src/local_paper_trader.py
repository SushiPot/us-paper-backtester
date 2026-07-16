from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import BacktestConfig, LocalPaperConfig
from .benchmark_gate import BenchmarkGateAnalyzer
from .candidate_rank import CandidateRankReporter
from .data import MarketDataLoader
from .database import get_store
from .fundamental_data import FundamentalDataAnalyzer
from .indicators import add_indicators
from .data_health import DataHealthChecker
from .factor_lab import FactorLabAnalyzer
from .loss_attribution import LossAttributionReporter
from .macro_data import MacroDataAnalyzer
from .market_environment import MarketEnvironmentAnalyzer
from .performance import PerformanceReportBuilder
from .relative_strength import RelativeStrengthRanker
from .signal_evaluation import SignalEvaluationAnalyzer
from .strategy import evaluate_buy_signal, should_sell_by_signal, signal_metric_snapshot
from .strategy_scorecard import StrategyScorecardBuilder
from .universe import UniverseFilter, filter_market_data_for_tradable, load_tradable_universe


@dataclass(frozen=True)
class LocalPosition:
    """本地虚拟持仓。"""

    symbol: str
    quantity: int
    avg_cost: float
    entry_date: pd.Timestamp
    strategy_name: str = "unknown"
    signal_score: float = 0.0
    last_price: float = 0.0
    market_value: float = 0.0
    unrealized_return_pct: float = 0.0


@dataclass(frozen=True)
class LocalDecision:
    """本地模拟盘单标的一次决策。"""

    symbol: str
    signal_type: str
    strategy_name: str
    signal_score: float
    buy_condition_met: bool
    sell_condition_met: bool
    risk_passed: bool
    order_submitted: bool
    reject_reason: str
    close: float = 0.0
    fast_ma: float = 0.0
    slow_ma: float = 0.0
    ma_gap_pct: float = 0.0
    rsi: float = 0.0
    volume_ratio: float = 0.0
    distance_fast_ma: float = 0.0
    return_5d: float = 0.0


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
    strategy_name: str
    signal_score: float
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
        self._refresh_loss_controls(market_data, account, positions, market_date)

        print(f"[STATUS] market_date={market_date.date()}", flush=True)
        print(f"[STATUS] virtual_cash={account['virtual_cash']:.2f}", flush=True)
        print(f"[STATUS] 当前虚拟持仓数量={len(positions)}", flush=True)
        print(f"[STATUS] 当前虚拟账户权益={equity:.2f}", flush=True)

        if not self._account_risk_ok(account):
            reason = "触发账户风控，停止本次本地模拟盘交易"
            print(f"[EXIT] {reason}", flush=True)
            self._append_run_log("EXIT", reason)
            CandidateRankReporter(self.config, self.output_dir).run(market_data, [])
            self._save_positions(positions)
            self._save_account(account)
            self._append_account_history(account, market_date)
            self._write_report(account, positions)
            return

        decisions = self._make_decisions(market_data, account, positions, prices, previous_prices, market_date)
        CandidateRankReporter(self.config, self.output_dir).run(market_data, decisions)
        positions = self._mark_positions_to_market(positions, prices)
        account["equity"] = self._calculate_equity(account["virtual_cash"], positions)
        account["peak_equity"] = max(account["peak_equity"], account["equity"])
        self._refresh_loss_controls(market_data, account, positions, market_date)

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
            max_new_symbol_downloads_per_run=self.config.max_new_symbol_downloads_per_run,
            market_data_primary_source=self.config.market_data_primary_source,
            market_data_request_interval_seconds=self.config.market_data_request_interval_seconds,
        )
        raw_data = MarketDataLoader(data_config).download_all()
        DataHealthChecker(data_config, self.output_dir).run()
        MarketEnvironmentAnalyzer(data_config, self.output_dir).run()
        MacroDataAnalyzer(output_dir=self.output_dir).run()
        FundamentalDataAnalyzer(output_dir=self.output_dir).run()
        data = {
            symbol: add_indicators(frame, self.config.fast_ma, self.config.slow_ma, self.config.rsi_period)
            for symbol, frame in raw_data.items()
        }
        UniverseFilter(self.config, self.output_dir).run(data)
        tradable_data = filter_market_data_for_tradable(data, self.output_dir)
        SignalEvaluationAnalyzer(self.config, self.output_dir).run(tradable_data)
        RelativeStrengthRanker(self.config, self.output_dir).run(tradable_data)
        FactorLabAnalyzer(self.config, self.output_dir).run(tradable_data)
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
        order_decision_used = any(position.entry_date.normalize() == market_date.normalize() for position in positions.values())
        relative_strength = self._relative_strength_lookup()
        environment_gate = self._environment_gate_state()
        tradable_universe = load_tradable_universe(self.output_dir)

        for symbol in self._decision_symbols(market_data, positions):
            print(f"[CHECK] 生成 {symbol} 本地模拟盘决策", flush=True)
            frame = market_data.get(symbol)
            if frame is None or frame.empty:
                decisions.append(self._reject(symbol, "NONE", "行情数据为空"))
                continue

            clean_frame = frame.dropna()
            if clean_frame.empty:
                if self._is_watch_only(symbol) and symbol not in positions:
                    decisions.append(self._reject(symbol, "HOLD", "观察标的，仅记录行情，不开新仓；指标数据不足"))
                else:
                    decisions.append(self._reject(symbol, "NONE", "指标数据为空"))
                continue

            latest = clean_frame.iloc[-1]
            metrics = signal_metric_snapshot(latest)
            price = prices.get(symbol, 0.0)
            previous_price = previous_prices.get(symbol, 0.0)
            price_ok, price_reason = self._validate_price(symbol, price, previous_price)
            if not price_ok:
                decisions.append(self._reject(symbol, "NONE", price_reason))
                continue

            position = positions.get(symbol)
            if self._is_watch_only(symbol) and not position:
                decisions.append(
                    LocalDecision(
                        symbol,
                        "HOLD",
                        "watch_only",
                        0.0,
                        False,
                        False,
                        False,
                        False,
                        "观察标的，仅记录行情，不开新仓",
                        **_decision_metric_kwargs(metrics),
                    )
                )
                continue
            buy_evaluation = evaluate_buy_signal(
                latest,
                rsi_limit=self.config.rsi_limit,
                enabled_strategies=self.config.enabled_buy_strategies,
                trend_min_rsi=self.config.trend_min_rsi,
                trend_volume_ratio=self.config.trend_volume_ratio,
                trend_max_distance_fast_ma=self.config.trend_max_distance_fast_ma,
                trend_min_return_5d=self.config.trend_min_return_5d,
            )
            technical_buy_met = buy_evaluation.should_buy
            buy_met = technical_buy_met
            buy_filter_reason = ""
            sell_reason = self._get_sell_reason(symbol, clean_frame, latest, position, price) if position else ""
            sell_met = bool(sell_reason)
            if technical_buy_met and not position:
                filter_ok, buy_filter_reason = self._buy_filters_ok(
                    symbol,
                    buy_evaluation.strategy_name,
                    relative_strength,
                    environment_gate,
                    tradable_universe,
                )
                buy_met = filter_ok
            signal_type = self._signal_type(buy_met, sell_met, position)

            if signal_type == "HOLD":
                reject_reason = buy_filter_reason or ("" if position else buy_evaluation.reason)
                decisions.append(
                    LocalDecision(
                        symbol,
                        "HOLD",
                        buy_evaluation.strategy_name,
                        buy_evaluation.score,
                        technical_buy_met,
                        sell_met,
                        not bool(buy_filter_reason),
                        False,
                        reject_reason,
                        **_decision_metric_kwargs(metrics),
                    )
                )
                continue

            is_risk_reducing_sell = (
                signal_type == "SELL"
                and bool(getattr(self.config, "allow_multiple_risk_reducing_sells", False))
            )
            if self.config.allow_one_order_per_run and order_decision_used and not is_risk_reducing_sell:
                decisions.append(
                    LocalDecision(
                        symbol,
                        signal_type,
                        buy_evaluation.strategy_name,
                        buy_evaluation.score,
                        technical_buy_met,
                        sell_met,
                        False,
                        False,
                        "本次运行已生成过一次订单决策",
                        **_decision_metric_kwargs(metrics),
                    )
                )
                continue

            if not is_risk_reducing_sell:
                order_decision_used = True
            if signal_type == "BUY":
                decision = self._execute_buy(
                    symbol,
                    price,
                    account,
                    positions,
                    technical_buy_met,
                    sell_met,
                    market_date,
                    buy_evaluation.strategy_name,
                    buy_evaluation.score,
                    buy_evaluation.reason,
                    metrics,
                )
            else:
                decision = self._execute_sell(
                    symbol,
                    price,
                    account,
                    positions,
                    buy_met,
                    sell_met,
                    sell_reason,
                    position.strategy_name if position else buy_evaluation.strategy_name,
                    position.signal_score if position else buy_evaluation.score,
                    metrics,
                )
            decisions.append(decision)

        return decisions

    def _decision_symbols(
        self,
        market_data: dict[str, pd.DataFrame],
        positions: dict[str, LocalPosition],
    ) -> list[str]:
        """只处理有行情数据或已有持仓的标的，避免扩池初期空数据刷屏。"""
        configured = list(self.config.symbols)
        data_symbols = {
            symbol
            for symbol, frame in market_data.items()
            if frame is not None and not frame.dropna(subset=["close"]).empty
        }
        ordered = [symbol for symbol in configured if symbol in data_symbols or symbol in positions]
        for symbol in positions:
            if symbol not in ordered:
                ordered.append(symbol)
        return ordered

    def _execute_buy(
        self,
        symbol: str,
        price: float,
        account: dict[str, float | str],
        positions: dict[str, LocalPosition],
        buy_met: bool,
        sell_met: bool,
        market_date: pd.Timestamp,
        strategy_name: str,
        signal_score: float,
        buy_reason: str,
        metrics: dict[str, object] | None = None,
    ) -> LocalDecision:
        risk_ok, reject_reason, quantity = self._buy_risk_ok(symbol, price, account, positions, strategy_name)
        order_reason = reject_reason if not risk_ok else f"{strategy_name}: {buy_reason}"
        self._append_order_log(
            symbol,
            "BUY",
            quantity,
            price,
            "REJECTED" if not risk_ok else "LOCAL_SIMULATED",
            order_reason,
            strategy_name,
            signal_score,
        )
        if not risk_ok:
            return LocalDecision(
                symbol,
                "BUY",
                strategy_name,
                signal_score,
                buy_met,
                sell_met,
                False,
                False,
                reject_reason,
                **_decision_metric_kwargs(metrics),
            )

        fill = self._simulate_fill(symbol, "BUY", quantity, price, f"{strategy_name}: {buy_reason}", strategy_name, signal_score)
        if fill.net_cash_change > float(account["virtual_cash"]):
            reason = "含滑点和手续费后虚拟现金不足，禁止杠杆"
            self._append_order_log(symbol, "BUY", quantity, price, "REJECTED", reason, strategy_name, signal_score)
            return LocalDecision(
                symbol,
                "BUY",
                strategy_name,
                signal_score,
                buy_met,
                sell_met,
                False,
                False,
                reason,
                **_decision_metric_kwargs(metrics),
            )

        account["virtual_cash"] = float(account["virtual_cash"]) - fill.net_cash_change
        positions[symbol] = LocalPosition(
            symbol=symbol,
            quantity=quantity,
            avg_cost=fill.fill_price,
            entry_date=market_date.normalize(),
            strategy_name=strategy_name,
            signal_score=signal_score,
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
        return LocalDecision(
            symbol,
            "BUY",
            strategy_name,
            signal_score,
            buy_met,
            sell_met,
            True,
            True,
            "",
            **_decision_metric_kwargs(metrics),
        )

    def _execute_sell(
        self,
        symbol: str,
        price: float,
        account: dict[str, float | str],
        positions: dict[str, LocalPosition],
        buy_met: bool,
        sell_met: bool,
        reason: str,
        strategy_name: str,
        signal_score: float,
        metrics: dict[str, object] | None = None,
    ) -> LocalDecision:
        position = positions.get(symbol)
        if not position:
            self._append_order_log(symbol, "SELL", 0, price, "REJECTED", "没有虚拟持仓，禁止做空", strategy_name, signal_score)
            return LocalDecision(
                symbol,
                "SELL",
                strategy_name,
                signal_score,
                buy_met,
                sell_met,
                False,
                False,
                "没有虚拟持仓，禁止做空",
                **_decision_metric_kwargs(metrics),
            )

        fill = self._simulate_fill(symbol, "SELL", position.quantity, price, reason, strategy_name, signal_score)
        self._append_order_log(symbol, "SELL", position.quantity, price, "LOCAL_SIMULATED", reason, strategy_name, signal_score)
        account["virtual_cash"] = float(account["virtual_cash"]) + fill.net_cash_change
        del positions[symbol]
        self._append_trade_log(fill, float(account["virtual_cash"]))
        print(
            f"[ORDER] SELL {symbol} qty={position.quantity} signal={price:.2f} fill={fill.fill_price:.2f} "
            f"commission={fill.commission:.2f}",
            flush=True,
        )
        return LocalDecision(
            symbol,
            "SELL",
            strategy_name,
            signal_score,
            buy_met,
            sell_met,
            True,
            True,
            "",
            **_decision_metric_kwargs(metrics),
        )

    def _simulate_fill(
        self,
        symbol: str,
        action: str,
        quantity: int,
        signal_price: float,
        reason: str,
        strategy_name: str = "unknown",
        signal_score: float = 0.0,
    ) -> Fill:
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
            strategy_name=strategy_name,
            signal_score=signal_score,
            reason=reason,
        )

    def _buy_risk_ok(
        self,
        symbol: str,
        price: float,
        account: dict[str, float | str],
        positions: dict[str, LocalPosition],
        strategy_name: str,
    ) -> tuple[bool, str, int]:
        if symbol in positions:
            return False, "已有持仓，跳过买入", 0
        if len(positions) >= self.config.max_positions:
            return False, "超过最大同时持仓数量", 0

        max_position_pct = self.config.special_max_position_pct.get(symbol, self.config.max_position_pct)
        if strategy_name == "trend_follow":
            max_position_pct *= self.config.trend_position_scale
        max_amount = float(account["equity"]) * max_position_pct
        quantity = int(min(max_amount, float(account["virtual_cash"])) // (price * (1 + self.config.slippage_pct)))
        if quantity <= 0:
            return False, "虚拟现金不足，无法买入整数股", 0

        estimated_fill = self._simulate_fill(symbol, "BUY", quantity, price, "风险预估")
        if estimated_fill.net_cash_change > float(account["virtual_cash"]):
            return False, "含滑点和手续费后虚拟现金不足，禁止杠杆", quantity
        if estimated_fill.net_cash_change > max_amount + self.config.min_commission:
            return False, f"超过单笔 {max_position_pct:.0%} 仓位限制", quantity
        return True, "", quantity

    def _buy_filters_ok(
        self,
        symbol: str,
        strategy_name: str,
        relative_strength: dict[str, dict[str, object]],
        environment_gate: dict[str, object],
        tradable_universe: set[str],
    ) -> tuple[bool, str]:
        """买入前的收益质量过滤：环境不好少买，弱势标的不买。"""
        action = str(environment_gate.get("action", "ALLOW_NORMAL_SIMULATION"))
        reasons = []

        if self._is_watch_only(symbol):
            return False, "观察标的，仅记录行情，不开新仓"
        if tradable_universe and symbol not in tradable_universe:
            return False, "股票池过滤未通过，禁止新买入"

        if action == "PAUSE_NEW_BUYS":
            return False, f"市场/宏观环境禁止新买入: {environment_gate.get('reason', '')}"

        profit_ok, profit_reason = self._profit_quality_gate_ok(strategy_name)
        if not profit_ok:
            return False, profit_reason

        rank_limit = int(environment_gate.get("rank_limit", self.config.relative_strength_top_n))
        min_score = float(environment_gate.get("min_score", self.config.relative_strength_min_score))
        if action == "REDUCE_NEW_BUY_SIZE":
            rank_limit = min(rank_limit, self.config.neutral_relative_strength_top_n)

        if self.config.enable_relative_strength_filter:
            row = relative_strength.get(symbol)
            if not row:
                return False, "缺少相对强弱排名，禁止新买入"
            rank = int(float(row.get("rank", 999)))
            score = float(row.get("relative_strength_score", 0.0))
            status = str(row.get("status", "WATCH"))
            if rank > rank_limit:
                reasons.append(f"相对强弱排名过低: rank={rank}, limit={rank_limit}")
            if score < min_score:
                reasons.append(f"相对强弱分数过低: score={score:.2f}")
            if status != "PASS":
                reasons.append(f"相对强弱状态不是PASS: {status}")

        if reasons:
            return False, "；".join(reasons)
        return True, ""

    def _profit_quality_gate_ok(self, strategy_name: str) -> tuple[bool, str]:
        """只有历史证据支持时才允许新买入，避免弱策略继续扩大亏损。"""
        if not bool(getattr(self.config, "enable_profit_quality_gate", True)):
            return True, ""

        reasons: list[str] = []
        signal_ok, signal_reason = self._profit_gate_signal_ok(strategy_name)
        if not signal_ok:
            reasons.append(signal_reason)

        factor_ok, factor_reason = self._profit_gate_factor_ok()
        if not factor_ok:
            reasons.append(factor_reason)

        benchmark_ok, benchmark_reason = self._profit_gate_benchmark_ok()
        if not benchmark_ok:
            reasons.append(benchmark_reason)

        if reasons:
            return False, "Profit Gate 暂停新买入: " + "；".join(reasons)
        return True, ""

    def _profit_gate_signal_ok(self, strategy_name: str) -> tuple[bool, str]:
        summary = self._read_output_csv("signal_evaluation_summary.csv")
        if summary.empty:
            return False, "缺少信号评估"

        eligible = summary.copy()
        if "signal_count" in eligible.columns:
            min_count = int(getattr(self.config, "profit_gate_min_signal_count", 100))
            eligible = eligible[pd.to_numeric(eligible["signal_count"], errors="coerce").fillna(0) >= min_count]
        if eligible.empty:
            return False, "信号样本不足"

        strategy_rows = eligible[eligible.get("strategy_name", pd.Series(dtype=str)).astype(str).isin(
            ["enabled_blend_relative_strength_filter", strategy_name]
        )]
        if strategy_rows.empty:
            strategy_rows = eligible

        precision = pd.to_numeric(strategy_rows.get("precision", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        edge = pd.to_numeric(strategy_rows.get("edge_vs_all_future_return", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        min_precision = float(getattr(self.config, "profit_gate_min_signal_precision", 0.40))
        min_edge = float(getattr(self.config, "profit_gate_min_signal_edge", 0.001))
        passed = (precision >= min_precision) & (edge >= min_edge)
        if bool(passed.any()):
            return True, ""

        best_index = edge.sort_values(ascending=False).index[0]
        return (
            False,
            "信号 edge/precision 未达标 "
            f"best_edge={float(edge.loc[best_index]):.2%}<{min_edge:.2%}, "
            f"best_precision={float(precision.loc[best_index]):.1%}<{min_precision:.1%}",
        )

    def _profit_gate_factor_ok(self) -> tuple[bool, str]:
        summary = self._read_output_csv("factor_lab_summary.csv")
        if summary.empty:
            return False, "缺少因子实验室结果"
        row = summary.iloc[0]
        status = str(row.get("status", "UNKNOWN"))
        score = _clean_number(row.get("factor_score", 0.0), 0.0)
        min_score = float(getattr(self.config, "profit_gate_min_factor_score", 50.0))
        if status == "WEAK" or score < min_score:
            return False, f"因子强度不足 status={status}, score={score:.1f}<{min_score:.1f}"
        return True, ""

    def _profit_gate_benchmark_ok(self) -> tuple[bool, str]:
        if not bool(getattr(self.config, "profit_gate_block_when_losing", True)):
            return True, ""
        summary = self._read_output_csv("benchmark_gate_summary.csv")
        if summary.empty:
            return True, ""
        row = summary.iloc[-1]
        action = str(row.get("recommended_action", ""))
        local_return = _clean_number(row.get("local_return", 0.0), 0.0)
        excess_return = _clean_number(row.get("excess_return", 0.0), 0.0)
        if action != "ALLOW_NORMAL_SIMULATION" and (local_return < 0 or excess_return < 0):
            return False, f"本地模拟仍亏损或落后基准 local={local_return:.2%}, excess={excess_return:.2%}"
        return True, ""

    def _relative_strength_lookup(self) -> dict[str, dict[str, object]]:
        frame = self._read_output_csv("relative_strength_rank.csv")
        if frame.empty:
            return {}
        return {str(row["symbol"]): row.to_dict() for _, row in frame.iterrows() if str(row.get("symbol", "")).strip()}

    def _environment_gate_state(self) -> dict[str, object]:
        actions = []
        reasons = []
        rank_limit = self.config.relative_strength_top_n
        min_score = self.config.relative_strength_min_score
        if self.config.enable_market_environment_gate:
            market = self._read_output_csv("market_environment_summary.csv")
            if not market.empty:
                row = market.iloc[-1]
                actions.append(str(row.get("recommended_action", "")))
                reasons.append(f"market={row.get('market_status', '')}/{row.get('recommended_action', '')}")
        if self.config.enable_macro_environment_gate:
            macro = self._read_output_csv("macro_environment_summary.csv")
            if not macro.empty:
                row = macro.iloc[-1]
                actions.append(str(row.get("recommended_action", "")))
                reasons.append(f"macro={row.get('macro_status', '')}/{row.get('recommended_action', '')}")
        if self.config.enable_strategy_health_gate:
            health = self._read_output_csv("strategy_health.csv")
            if not health.empty:
                row = health.iloc[-1]
                health_action = str(row.get("recommended_action", ""))
                health_status = str(row.get("health_status", ""))
                reasons.append(f"strategy_health={health_status}/{health_action}")
                if health_action == "PAUSE_NEW_BUYS":
                    actions.append("PAUSE_NEW_BUYS")
                elif health_action in {"OBSERVE_ONLY", "REDUCED_SIZE", "REDUCED_SIZE_OR_PAUSE_BUYS"}:
                    actions.append("REDUCE_NEW_BUY_SIZE")
                    rank_limit = min(rank_limit, self.config.observation_relative_strength_top_n)
                    min_score = max(min_score, self.config.observation_relative_strength_min_score)
        if self.config.enable_benchmark_gate:
            benchmark = self._read_output_csv("benchmark_gate_summary.csv")
            if not benchmark.empty:
                row = benchmark.iloc[-1]
                benchmark_action = str(row.get("recommended_action", ""))
                benchmark_status = str(row.get("status", ""))
                reasons.append(f"benchmark={benchmark_status}/{benchmark_action}")
                if benchmark_action == "PAUSE_NEW_BUYS":
                    actions.append("PAUSE_NEW_BUYS")
                elif benchmark_action in {"REDUCE_NEW_BUY_SIZE", "OBSERVE_ONLY"}:
                    actions.append("REDUCE_NEW_BUY_SIZE")
                    rank_limit = min(rank_limit, self.config.observation_relative_strength_top_n)
                    min_score = max(min_score, self.config.observation_relative_strength_min_score)

        if "PAUSE_NEW_BUYS" in actions:
            action = "PAUSE_NEW_BUYS"
        elif "REDUCE_NEW_BUY_SIZE" in actions or "OBSERVE_ONLY" in actions:
            action = "REDUCE_NEW_BUY_SIZE"
        else:
            action = "ALLOW_NORMAL_SIMULATION"
        return {
            "action": action,
            "rank_limit": rank_limit,
            "min_score": min_score,
            "reason": "; ".join(reason for reason in reasons if reason),
        }

    def _is_watch_only(self, symbol: str) -> bool:
        return symbol in set(getattr(self.config, "watch_only_symbols", []))

    def _read_output_csv(self, filename: str) -> pd.DataFrame:
        path = self.output_dir / filename
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

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
        holding_days = int(((frame.index > position.entry_date) & (frame.index <= frame.index[-1])).sum())

        if should_sell_by_signal(latest):
            return "MA20下穿MA60"
        if return_pct >= self.config.take_profit_pct:
            return "止盈"

        active_stop_loss = self._active_stop_loss()
        if return_pct <= active_stop_loss:
            return f"动态止损 {return_pct:.2%} <= {active_stop_loss:.2%}"

        if self.config.enable_dynamic_exit:
            environment_gate = self._environment_gate_state()
            action = str(environment_gate.get("action", "ALLOW_NORMAL_SIMULATION"))
            if action == "PAUSE_NEW_BUYS" and return_pct < 0:
                return "基准/环境闸门暂停新买入，亏损仓位退出"

            peak_close = self._peak_close_since_entry(frame, position.entry_date)
            drawdown_from_peak = price / peak_close - 1 if peak_close > 0 else 0.0
            if holding_days >= 3 and drawdown_from_peak <= self.config.trailing_stop_pct:
                return f"移动止损 {drawdown_from_peak:.2%} <= {self.config.trailing_stop_pct:.2%}"

            fast_ma = float(latest.get("fast_ma", 0.0))
            if (
                holding_days >= self.config.stagnant_exit_days
                and return_pct <= self.config.stagnant_exit_max_return_pct
                and fast_ma > 0
                and price < fast_ma
            ):
                return "持仓滞涨且跌破MA20"

        if holding_days > self.config.max_holding_days:
            return "持仓超过30个交易日"
        return ""

    def _active_stop_loss(self) -> float:
        active_stop_loss = self.config.stop_loss_pct
        if not self.config.enable_dynamic_exit:
            return active_stop_loss

        action = str(self._environment_gate_state().get("action", "ALLOW_NORMAL_SIMULATION"))
        if action == "PAUSE_NEW_BUYS":
            active_stop_loss = max(active_stop_loss, self.config.risk_off_stop_loss_pct)
        elif action == "REDUCE_NEW_BUY_SIZE":
            active_stop_loss = max(active_stop_loss, self.config.neutral_stop_loss_pct)
        return active_stop_loss

    @staticmethod
    def _peak_close_since_entry(frame: pd.DataFrame, entry_date: pd.Timestamp) -> float:
        since_entry = frame.loc[frame.index >= pd.Timestamp(entry_date)]
        if since_entry.empty:
            since_entry = frame
        if since_entry.empty or "close" not in since_entry.columns:
            return 0.0
        return float(since_entry["close"].astype(float).max())

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
                strategy_name=position.strategy_name,
                signal_score=position.signal_score,
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

        frame = pd.read_csv(path)
        if frame.empty:
            print("[WARN] 虚拟账户文件没有数据行，使用初始虚拟资金重建账户状态", flush=True)
            return {
                "as_of_date": market_date.date().isoformat(),
                "virtual_cash": self.config.initial_cash,
                "equity": self.config.initial_cash,
                "daily_start_equity": self.config.initial_cash,
                "peak_equity": self.config.initial_cash,
            }

        row = frame.iloc[-1]
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
        get_store().append_frame("accounts", row)

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
        get_store().append_frame("account_history", row)

    def _load_positions(self) -> dict[str, LocalPosition]:
        path = self.output_dir / self.config.positions_file
        if not path.exists() or path.stat().st_size == 0:
            return {}
        frame = pd.read_csv(path, parse_dates=["entry_date"])
        strategy_lookup = self._open_strategy_by_symbol()
        positions = {}
        for _, row in frame.iterrows():
            if pd.isna(row.get("symbol")):
                continue
            symbol = str(row["symbol"])
            inferred = strategy_lookup.get(symbol, {})
            strategy_name = _clean_text(row.get("strategy_name", ""), "")
            if not strategy_name or strategy_name in {"unknown", "unattributed"}:
                strategy_name = _clean_text(inferred.get("strategy_name", "unknown"), "unknown")
            signal_score = _clean_number(row.get("signal_score", 0.0), 0.0)
            if signal_score == 0.0:
                signal_score = _clean_number(inferred.get("signal_score", 0.0), 0.0)
            positions[str(row["symbol"])] = LocalPosition(
                symbol=symbol,
                quantity=int(row["quantity"]),
                avg_cost=float(row["avg_cost"]),
                entry_date=pd.Timestamp(row["entry_date"]),
                strategy_name=strategy_name,
                signal_score=signal_score,
                last_price=float(row.get("last_price", row["avg_cost"])),
                market_value=float(row.get("market_value", int(row["quantity"]) * float(row["avg_cost"]))),
                unrealized_return_pct=float(row.get("unrealized_return_pct", 0.0)),
            )
        return positions

    def _open_strategy_by_symbol(self) -> dict[str, dict[str, object]]:
        path = self.output_dir / self.config.paper_trade_log_file
        if not path.exists() or path.stat().st_size == 0:
            return {}
        try:
            trades = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return {}

        open_state: dict[str, dict[str, object]] = {}
        quantities: dict[str, int] = {}
        for _, row in trades.iterrows():
            symbol = _clean_text(row.get("symbol", ""), "")
            if not symbol:
                continue
            action = _clean_text(row.get("action", ""), "").upper()
            quantity = int(_clean_number(row.get("quantity", 0), 0.0))
            if quantity <= 0:
                continue
            if action == "BUY":
                quantities[symbol] = quantities.get(symbol, 0) + quantity
                open_state[symbol] = {
                    "strategy_name": _strategy_from_reason(row),
                    "signal_score": _clean_number(row.get("signal_score", 0.0), 0.0),
                }
            elif action == "SELL":
                quantities[symbol] = max(0, quantities.get(symbol, 0) - quantity)
                if quantities[symbol] == 0:
                    open_state.pop(symbol, None)
        return open_state

    def _save_positions(self, positions: dict[str, LocalPosition]) -> None:
        rows = [
            {
                "symbol": position.symbol,
                "quantity": position.quantity,
                "avg_cost": position.avg_cost,
                "entry_date": position.entry_date,
                "strategy_name": position.strategy_name,
                "signal_score": position.signal_score,
                "last_price": position.last_price,
                "market_value": position.market_value,
                "unrealized_return_pct": position.unrealized_return_pct,
            }
            for position in positions.values()
        ]
        frame = pd.DataFrame(
            rows,
            columns=[
                "symbol",
                "quantity",
                "avg_cost",
                "entry_date",
                "strategy_name",
                "signal_score",
                "last_price",
                "market_value",
                "unrealized_return_pct",
            ],
        )
        frame.to_csv(self.output_dir / self.config.positions_file, index=False, encoding="utf-8-sig")
        get_store().replace_positions(frame)

    def _append_order_log(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        status: str,
        reason: str,
        strategy_name: str = "unknown",
        signal_score: float = 0.0,
    ) -> None:
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
                    "strategy_name": strategy_name,
                    "signal_score": signal_score,
                    "reason": reason,
                }
            ]
        )
        _append_csv(self.output_dir / self.config.paper_order_log_file, row)
        get_store().append_frame("orders", row)

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
                    "strategy_name": fill.strategy_name,
                    "signal_score": fill.signal_score,
                    "reason": fill.reason,
                }
            ]
        )
        _append_csv(self.output_dir / self.config.paper_trade_log_file, row)
        get_store().append_frame("trades", row)

    def _append_decision_log(self, decisions: list[LocalDecision]) -> None:
        rows = [
            {
                "time": pd.Timestamp.now(),
                "symbol": decision.symbol,
                "signal_type": decision.signal_type,
                "strategy_name": decision.strategy_name,
                "signal_score": decision.signal_score,
                "buy_condition_met": decision.buy_condition_met,
                "sell_condition_met": decision.sell_condition_met,
                "risk_passed": decision.risk_passed,
                "order_submitted": decision.order_submitted,
                "reject_reason": decision.reject_reason,
                "close": decision.close,
                "fast_ma": decision.fast_ma,
                "slow_ma": decision.slow_ma,
                "ma_gap_pct": decision.ma_gap_pct,
                "rsi": decision.rsi,
                "volume_ratio": decision.volume_ratio,
                "distance_fast_ma": decision.distance_fast_ma,
                "return_5d": decision.return_5d,
            }
            for decision in decisions
        ]
        frame = pd.DataFrame(rows)
        _append_csv(self.output_dir / self.config.decision_log_file, frame)
        get_store().append_frame("decisions", frame)

    def _append_run_log(self, event_type: str, message: str) -> None:
        row = pd.DataFrame([{"time": pd.Timestamp.now(), "event_type": event_type, "message": message}])
        _append_csv(self.output_dir / self.config.run_log_file, row)
        get_store().append_frame("run_logs", row)

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
            PerformanceReportBuilder(self.output_dir).build_from_equity_csv(
                self.config.account_history_file,
                self.config.local_performance_report_file,
                self.config.local_performance_metrics_file,
                "Local Paper Trading Performance Report",
            )
        else:
            report["max_drawdown"] = 0.0
            report["sharpe_ratio"] = 0.0

        frame = pd.DataFrame([report])
        frame.to_csv(
            self.output_dir / self.config.local_report_file,
            index=False,
            encoding="utf-8-sig",
        )
        get_store().append_generic_frame("local_paper_reports", self.config.local_report_file, frame)
        StrategyScorecardBuilder(self.config, self.output_dir).run()
        LossAttributionReporter(self.config, self.output_dir).run(account, positions)

    def _refresh_loss_controls(
        self,
        market_data: dict[str, pd.DataFrame],
        account: dict[str, float | str],
        positions: dict[str, LocalPosition],
        market_date: pd.Timestamp,
    ) -> None:
        BenchmarkGateAnalyzer(self.config, self.output_dir).run(market_data, account, market_date)
        LossAttributionReporter(self.config, self.output_dir).run(account, positions)

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
        return LocalDecision(symbol, signal_type, "none", 0.0, False, False, False, False, reason)

    def _ensure_output_files(self) -> None:
        """即使当天没有订单/成交，也创建标准输出文件表头。"""
        files = {
            self.config.positions_file: [
                "symbol",
                "quantity",
                "avg_cost",
                "entry_date",
                "strategy_name",
                "signal_score",
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
                "strategy_name",
                "signal_score",
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
                "strategy_name",
                "signal_score",
                "reason",
            ],
            self.config.decision_log_file: [
                "time",
                "symbol",
                "signal_type",
                "strategy_name",
                "signal_score",
                "buy_condition_met",
                "sell_condition_met",
                "risk_passed",
                "order_submitted",
                "reject_reason",
                "close",
                "fast_ma",
                "slow_ma",
                "ma_gap_pct",
                "rsi",
                "volume_ratio",
                "distance_fast_ma",
                "return_5d",
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


def _clean_text(value: object, default: str) -> str:
    if pd.isna(value):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return default
    return text


def _clean_number(value: object, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _strategy_from_reason(row: pd.Series) -> str:
    strategy_name = _clean_text(row.get("strategy_name", ""), "")
    if strategy_name and strategy_name not in {"unknown", "unattributed"}:
        return strategy_name
    reason = _clean_text(row.get("reason", ""), "")
    if ":" in reason:
        return _clean_text(reason.split(":", 1)[0], "unknown")
    if "trend_follow" in reason:
        return "trend_follow"
    if "strict_golden_cross" in reason:
        return "strict_golden_cross"
    return "unknown"


def _decision_metric_kwargs(metrics: dict[str, object] | None) -> dict[str, float]:
    metrics = metrics or {}
    return {
        "close": _clean_number(metrics.get("close", 0.0), 0.0),
        "fast_ma": _clean_number(metrics.get("fast_ma", 0.0), 0.0),
        "slow_ma": _clean_number(metrics.get("slow_ma", 0.0), 0.0),
        "ma_gap_pct": _clean_number(metrics.get("ma_gap_pct", 0.0), 0.0),
        "rsi": _clean_number(metrics.get("rsi", 0.0), 0.0),
        "volume_ratio": _clean_number(metrics.get("volume_ratio", 0.0), 0.0),
        "distance_fast_ma": _clean_number(metrics.get("distance_fast_ma", 0.0), 0.0),
        "return_5d": _clean_number(metrics.get("return_5d", 0.0), 0.0),
    }
