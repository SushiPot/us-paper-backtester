from __future__ import annotations

import traceback

import pandas as pd

from .config import BacktestConfig, PaperTradingConfig
from .data import MarketDataLoader
from .ibkr_client import IBKRClient, PositionSnapshot
from .indicators import add_indicators
from .live_risk import LiveRiskManager, PositionStateStore, append_risk_log, is_regular_us_market_hours
from .order_manager import OrderIntent, OrderManager
from .strategy import should_buy, should_sell_by_signal


class PaperTrader:
    """IBKR Paper Trading ?????????? dry_run=True?"""

    def __init__(self, config: PaperTradingConfig) -> None:
        self.config = config
        self.client = IBKRClient(config)
        self.risk = LiveRiskManager(config)
        self.order_manager = OrderManager(config, self.client, self.risk)
        self.position_state = PositionStateStore(config.output_dir, config.paper_position_state_file)

    def run_once(self) -> None:
        try:
            self.client.connect()
            account = self.client.get_account_snapshot()
            positions = self.client.get_positions()
            account_decision = self.risk.update_account_risk(account)
            append_risk_log(
                self.config.output_dir,
                self.config.paper_risk_log_file,
                "ACCOUNT_CHECK",
                f"{account.account}: {account_decision.reason}",
            )

            if not account_decision.allowed:
                return
            if self.config.enforce_regular_trading_hours and not is_regular_us_market_hours():
                append_risk_log(
                    self.config.output_dir,
                    self.config.paper_risk_log_file,
                    "MARKET_CLOSED",
                    "???????????????????????",
                )
                return

            market_data = self._load_strategy_data()
            for symbol in self.config.symbols:
                if symbol not in market_data:
                    continue
                self._process_symbol(symbol, market_data[symbol], account, positions)
        except Exception as exc:
            print(f"[ERROR] PaperTrader.run_once ??: {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
            append_risk_log(self.config.output_dir, self.config.paper_risk_log_file, "EXCEPTION", str(exc))
            raise
        finally:
            self.client.disconnect()

    def _load_strategy_data(self) -> dict[str, pd.DataFrame]:
        data_config = BacktestConfig(
            symbols=self.config.symbols,
            start_date=self.config.historical_start_date,
            output_dir=self.config.output_dir,
            retry_count=self.config.retry_count,
            retry_wait_seconds=self.config.retry_wait_seconds,
        )
        raw_data = MarketDataLoader(data_config).download_all()
        return {symbol: add_indicators(frame) for symbol, frame in raw_data.items()}

    def _process_symbol(
        self,
        symbol: str,
        frame: pd.DataFrame,
        account,
        positions: dict[str, PositionSnapshot],
    ) -> None:
        latest = frame.dropna().iloc[-1]
        try:
            market_price = self.client.get_market_price(symbol)
        except Exception as exc:
            print(f"[ERROR] {symbol} ??????: {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
            if not self.config.dry_run:
                raise
            market_price = float(latest["close"])
            append_risk_log(
                self.config.output_dir,
                self.config.paper_risk_log_file,
                "MARKET_DATA_FALLBACK",
                f"{symbol} ???????dry_run ???????: {exc}",
            )

        position = positions.get(symbol)
        if position:
            sell_reason = self._get_sell_reason(symbol, frame, latest, position, market_price)
            if sell_reason:
                intent = OrderIntent(
                    symbol=symbol,
                    action="SELL",
                    quantity=position.quantity,
                    estimated_price=market_price,
                    reason=sell_reason,
                )
                self.order_manager.submit(intent, account, positions)
            return

        if should_buy(latest):
            max_position_pct = self.config.special_max_position_pct.get(symbol, self.config.max_position_pct)
            max_amount = account.net_liquidation * max_position_pct
            quantity = int(min(max_amount, account.available_funds) // market_price)
            if quantity <= 0:
                append_risk_log(
                    self.config.output_dir,
                    self.config.paper_risk_log_file,
                    "SKIP_ORDER",
                    f"{symbol} ??????????????",
                )
                return
            intent = OrderIntent(
                symbol=symbol,
                action="BUY",
                quantity=quantity,
                estimated_price=market_price,
                reason="MA20??MA60?RSI<70???",
            )
            self.order_manager.submit(intent, account, positions)

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
            return "MA20??MA60"
        if return_pct <= self.config.stop_loss_pct:
            return "??"
        if return_pct >= self.config.take_profit_pct:
            return "??"

        entry_date = self.position_state.get_entry_date(symbol)
        if entry_date is not None:
            holding_days = int(((frame.index > entry_date) & (frame.index <= frame.index[-1])).sum())
            if holding_days > self.config.max_holding_days:
                return "????30????"

        # IBKR positions ?????????????????????????????????
        return ""
