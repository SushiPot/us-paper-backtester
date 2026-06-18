from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf

from .config import OptionsResearchConfig
from .database import get_store


@dataclass(frozen=True)
class OptionResearchResult:
    """期权研究输出摘要。"""

    contract_count: int
    symbol_count: int
    liquid_contract_count: int
    output_file: str


class OptionsResearchScanner:
    """股票/ETF 期权链扫描器。研究用途，不生成任何订单。"""

    def __init__(self, config: OptionsResearchConfig | None = None) -> None:
        self.config = config or OptionsResearchConfig()
        self.output_dir = self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> OptionResearchResult:
        rows: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        for symbol in self.config.symbols:
            try:
                rows.extend(self._scan_symbol(symbol))
            except Exception as exc:
                errors.append(
                    {
                        "time": pd.Timestamp.now(),
                        "symbol": symbol,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values(["symbol", "expiration", "option_type", "liquidity_score"], ascending=[True, True, True, False])
        frame.to_csv(self.output_dir / "options_chain_snapshot.csv", index=False, encoding="utf-8-sig")

        liquid = frame[frame["research_passed"]] if not frame.empty and "research_passed" in frame.columns else pd.DataFrame()
        liquid.to_csv(self.output_dir / "options_liquidity_watchlist.csv", index=False, encoding="utf-8-sig")
        summary = self._summary(frame, liquid, errors)
        summary.to_csv(self.output_dir / "options_research_summary.csv", index=False, encoding="utf-8-sig")
        self._write_report(summary, errors)

        get_store().append_generic_frame("options_chain_snapshot", "options_chain_snapshot.csv", frame)
        get_store().append_generic_frame("options_research_summary", "options_research_summary.csv", summary)

        if errors:
            error_frame = pd.DataFrame(errors)
            error_frame.to_csv(self.output_dir / "options_research_errors.csv", index=False, encoding="utf-8-sig")
            get_store().append_generic_frame("options_research_errors", "options_research_errors.csv", error_frame)

        return OptionResearchResult(
            contract_count=int(len(frame)),
            symbol_count=int(frame["symbol"].nunique()) if not frame.empty else 0,
            liquid_contract_count=int(len(liquid)),
            output_file="outputs/options_research_summary.csv",
        )

    def _scan_symbol(self, symbol: str) -> list[dict[str, object]]:
        ticker = yf.Ticker(symbol)
        expirations = list(ticker.options or [])[: self.config.max_expirations_per_symbol]
        if not expirations:
            return []

        price = self._latest_price(ticker)
        rows = []
        for expiration in expirations:
            chain = ticker.option_chain(expiration)
            if self.config.include_calls:
                rows.extend(self._rows_from_chain(symbol, expiration, "CALL", chain.calls, price))
            if self.config.include_puts:
                rows.extend(self._rows_from_chain(symbol, expiration, "PUT", chain.puts, price))
        return rows

    def _rows_from_chain(
        self,
        symbol: str,
        expiration: str,
        option_type: str,
        frame: pd.DataFrame,
        underlying_price: float,
    ) -> list[dict[str, object]]:
        rows = []
        if frame.empty:
            return rows
        for _, row in frame.iterrows():
            strike = _number(row.get("strike", 0.0))
            bid = _number(row.get("bid", 0.0))
            ask = _number(row.get("ask", 0.0))
            last_price = _number(row.get("lastPrice", 0.0))
            volume = int(_number(row.get("volume", 0.0)))
            open_interest = int(_number(row.get("openInterest", 0.0)))
            implied_volatility = _number(row.get("impliedVolatility", 0.0))
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last_price
            spread_pct = (ask - bid) / mid if mid > 0 and ask >= bid else 1.0
            moneyness = strike / underlying_price - 1 if underlying_price > 0 else 0.0
            liquidity_score = open_interest * 0.7 + volume * 0.3
            research_passed = (
                open_interest >= self.config.min_open_interest
                and spread_pct <= self.config.max_spread_pct
                and abs(moneyness) <= self.config.moneyness_window_pct
                and mid > 0
            )
            rows.append(
                {
                    "time": pd.Timestamp.now(),
                    "symbol": symbol,
                    "underlying_price": underlying_price,
                    "expiration": expiration,
                    "option_type": option_type,
                    "contract_symbol": row.get("contractSymbol", ""),
                    "strike": strike,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "last_price": last_price,
                    "spread_pct": spread_pct,
                    "volume": volume,
                    "open_interest": open_interest,
                    "implied_volatility": implied_volatility,
                    "moneyness": moneyness,
                    "liquidity_score": liquidity_score,
                    "research_passed": research_passed,
                    "note": "research_only_no_orders",
                }
            )
        return rows

    @staticmethod
    def _latest_price(ticker: yf.Ticker) -> float:
        history = ticker.history(period="5d", auto_adjust=True)
        if history.empty or "Close" not in history.columns:
            return 0.0
        return float(history["Close"].dropna().iloc[-1])

    @staticmethod
    def _summary(frame: pd.DataFrame, liquid: pd.DataFrame, errors: list[dict[str, object]]) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(
                [
                    {
                        "time": pd.Timestamp.now(),
                        "contract_count": 0,
                        "symbol_count": 0,
                        "liquid_contract_count": 0,
                        "avg_spread_pct": 0.0,
                        "avg_implied_volatility": 0.0,
                        "error_count": len(errors),
                        "status": "NO_DATA",
                    }
                ]
            )
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "contract_count": len(frame),
                    "symbol_count": frame["symbol"].nunique(),
                    "liquid_contract_count": len(liquid),
                    "avg_spread_pct": float(frame["spread_pct"].mean()),
                    "avg_implied_volatility": float(frame["implied_volatility"].mean()),
                    "error_count": len(errors),
                    "status": "OK" if len(liquid) else "OBSERVE_ONLY",
                }
            ]
        )

    def _write_report(self, summary: pd.DataFrame, errors: list[dict[str, object]]) -> None:
        row = summary.iloc[0] if not summary.empty else {}
        lines = [
            "# Options Research Report",
            "",
            f"Generated at: {pd.Timestamp.now()}",
            "",
            "Scope: stocks and ETFs only. Crypto is excluded. This report is research-only and never creates orders.",
            "",
            f"- Contracts scanned: {row.get('contract_count', 0)}",
            f"- Symbols scanned: {row.get('symbol_count', 0)}",
            f"- Liquid watchlist contracts: {row.get('liquid_contract_count', 0)}",
            f"- Status: {row.get('status', 'NO_DATA')}",
            "",
        ]
        if errors:
            lines.extend(["## Errors", ""])
            for error in errors:
                lines.append(f"- {error['symbol']}: {error['error']}")
        (self.output_dir / "options_research_report.md").write_text("\n".join(lines), encoding="utf-8")


def _number(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0
