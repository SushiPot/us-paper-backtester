from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BacktestConfig
from .data import MarketDataLoader
from .database import get_store


@dataclass(frozen=True)
class AllocationSummary:
    """组合权重建议的摘要。"""

    method: str
    expected_annual_return: float
    annual_volatility: float
    sharpe_ratio: float
    stock_weight: float
    cash_weight: float
    fallback_reason: str = ""


class PortfolioAllocationOptimizer:
    """生成长仓、无杠杆、单标的不超过上限的目标权重建议。"""

    def __init__(
        self,
        config: BacktestConfig | None = None,
        output_dir: Path = Path("outputs"),
        target_equity: float | None = None,
    ) -> None:
        self.config = config or BacktestConfig()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.target_equity = target_equity or self.config.initial_cash

    def run(self) -> AllocationSummary:
        raw_data = MarketDataLoader(self.config).download_all()
        prices = self._close_prices(raw_data)
        if prices.empty or len(prices.columns) < 2:
            raise RuntimeError("组合优化需要至少两个标的的历史价格")

        fallback_reasons = []
        raw_weights, method, stats = self._optimize_with_riskfolio(prices)
        if stats.get("fallback_reason"):
            fallback_reasons.append(str(stats["fallback_reason"]))
        if not raw_weights:
            raw_weights, method, stats = self._optimize_with_pypfopt(prices)
            if stats.get("fallback_reason"):
                fallback_reasons.append(str(stats["fallback_reason"]))
        if not raw_weights:
            raw_weights, method, stats = self._inverse_volatility(prices)
            if stats.get("fallback_reason"):
                fallback_reasons.append(str(stats["fallback_reason"]))

        capped = self._cap_weights(raw_weights, self.config.max_position_pct, self.config.special_max_position_pct)
        rows = []
        for symbol in self.config.symbols:
            target_weight = capped.get(symbol, 0.0)
            max_position_pct = self.config.special_max_position_pct.get(symbol, self.config.max_position_pct)
            rows.append(
                {
                    "symbol": symbol,
                    "raw_weight": raw_weights.get(symbol, 0.0),
                    "target_weight": target_weight,
                    "target_amount": target_weight * self.target_equity,
                    "max_position_pct": max_position_pct,
                    "method": method,
                    "source": "online_yahoo",
                }
            )

        stock_weight = float(sum(capped.values()))
        cash_weight = max(0.0, 1.0 - stock_weight)
        rows.append(
            {
                "symbol": "CASH",
                "raw_weight": 0.0,
                "target_weight": cash_weight,
                "target_amount": cash_weight * self.target_equity,
                "max_position_pct": 1.0,
                "method": method,
                "source": "online_yahoo",
            }
        )

        allocation = pd.DataFrame(rows)
        allocation.to_csv(self.output_dir / "portfolio_allocation.csv", index=False, encoding="utf-8-sig")
        allocation.to_csv(self.output_dir / "online_portfolio_allocation.csv", index=False, encoding="utf-8-sig")
        get_store().replace_portfolio_allocations(allocation)

        summary = AllocationSummary(
            method=method,
            expected_annual_return=float(stats.get("expected_annual_return", 0.0)),
            annual_volatility=float(stats.get("annual_volatility", 0.0)),
            sharpe_ratio=float(stats.get("sharpe_ratio", 0.0)),
            stock_weight=stock_weight,
            cash_weight=cash_weight,
            fallback_reason=" | ".join(fallback_reasons),
        )
        summary_frame = pd.DataFrame([summary.__dict__])
        summary_frame.to_csv(
            self.output_dir / "portfolio_allocation_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )
        summary_frame.to_csv(
            self.output_dir / "online_portfolio_allocation_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )
        get_store().append_generic_frame("portfolio_allocation_summaries", "portfolio_allocation_summary.csv", summary_frame)
        get_store().append_generic_frame(
            "online_portfolio_allocation_summaries",
            "online_portfolio_allocation_summary.csv",
            summary_frame,
        )
        return summary

    def _close_prices(self, raw_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        min_history = max(self.config.slow_ma + 1, 120)
        valid_frames = {}
        skipped = []
        for symbol, frame in raw_data.items():
            if "close" not in frame.columns or frame["close"].dropna().shape[0] < min_history:
                skipped.append(symbol)
                continue
            valid_frames[symbol] = frame["close"].rename(symbol)

        if skipped:
            print(f"[WARN] 以下标的历史数据不足，暂不参与组合优化: {', '.join(skipped)}", flush=True)
        if not valid_frames:
            return pd.DataFrame()

        prices = pd.concat(
            valid_frames,
            axis=1,
        )
        prices = prices.dropna(how="all").ffill().dropna()
        return prices

    def _optimize_with_riskfolio(self, prices: pd.DataFrame) -> tuple[dict[str, float], str, dict[str, float]]:
        returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        if returns.empty or len(returns.columns) < 2:
            return {}, "", {"fallback_reason": "Riskfolio 需要至少两个标的的收益率数据"}

        try:
            import riskfolio as rp

            portfolio = rp.Portfolio(returns=returns)
            portfolio.assets_stats(method_mu="hist", method_cov="hist", d=0.94)
            weights_frame = portfolio.rp_optimization(model="Classic", rm="MV", rf=0, b=None, hist=True)
            if weights_frame is None or weights_frame.empty:
                raise RuntimeError("Riskfolio 没有返回有效权重")
            weights = weights_frame.iloc[:, 0].astype(float).to_dict()
            weights = {str(symbol): max(0.0, float(weight)) for symbol, weight in weights.items()}
            total_weight = sum(weights.values())
            if total_weight <= 0:
                raise RuntimeError("Riskfolio 返回的权重合计小于等于0")
            weights = {symbol: weight / total_weight for symbol, weight in weights.items()}
            stats = self._portfolio_stats(returns, weights)
            stats["fallback_reason"] = ""
            return weights, "riskfolio_risk_parity_mv_capped", stats
        except Exception as exc:
            reason = f"Riskfolio-Lib 不可用，降级到 PyPortfolioOpt: {type(exc).__name__}: {exc}"
            print(f"[WARN] {reason}", flush=True)
            return {}, "", {"fallback_reason": reason}

    def _optimize_with_pypfopt(self, prices: pd.DataFrame) -> tuple[dict[str, float], str, dict[str, float]]:
        try:
            from pypfopt import EfficientFrontier, expected_returns, risk_models

            mu = expected_returns.mean_historical_return(prices)
            cov = risk_models.sample_cov(prices)
            ef = EfficientFrontier(mu, cov, weight_bounds=(0.0, 1.0))
            ef.max_sharpe()
            weights = {symbol: float(weight) for symbol, weight in ef.clean_weights().items()}
            ret, vol, sharpe = ef.portfolio_performance(verbose=False)
            return (
                weights,
                "pypfopt_max_sharpe_capped",
                {
                    "expected_annual_return": float(ret),
                    "annual_volatility": float(vol),
                    "sharpe_ratio": float(sharpe),
                },
            )
        except Exception as exc:
            reason = f"PyPortfolioOpt 优化失败，使用逆波动率降级权重: {type(exc).__name__}: {exc}"
            print(f"[WARN] {reason}", flush=True)
            return {}, "", {"fallback_reason": reason}

    @staticmethod
    def _inverse_volatility(prices: pd.DataFrame) -> tuple[dict[str, float], str, dict[str, float]]:
        returns = prices.pct_change().dropna()
        volatility = returns.std(ddof=0).replace(0, np.nan)
        inverse_vol = (1 / volatility).replace([np.inf, -np.inf], np.nan).dropna()
        weights = (inverse_vol / inverse_vol.sum()).to_dict() if not inverse_vol.empty else {}
        portfolio_returns = returns[list(weights.keys())].mul(pd.Series(weights), axis=1).sum(axis=1) if weights else pd.Series(dtype=float)
        annual_return = float((1 + portfolio_returns.mean()) ** 252 - 1) if not portfolio_returns.empty else 0.0
        annual_volatility = float(portfolio_returns.std(ddof=0) * np.sqrt(252)) if portfolio_returns.std(ddof=0) > 0 else 0.0
        sharpe = float(annual_return / annual_volatility) if annual_volatility > 0 else 0.0
        return (
            {str(symbol): float(weight) for symbol, weight in weights.items()},
            "inverse_volatility_capped",
            {
                "expected_annual_return": annual_return,
                "annual_volatility": annual_volatility,
                "sharpe_ratio": sharpe,
                "fallback_reason": "使用逆波动率降级权重",
            },
        )

    @staticmethod
    def _portfolio_stats(returns: pd.DataFrame, weights: dict[str, float]) -> dict[str, float]:
        active_symbols = [symbol for symbol in returns.columns if symbol in weights]
        if not active_symbols:
            return {"expected_annual_return": 0.0, "annual_volatility": 0.0, "sharpe_ratio": 0.0}
        weight_series = pd.Series({symbol: weights[symbol] for symbol in active_symbols}, dtype=float)
        portfolio_returns = returns[active_symbols].mul(weight_series, axis=1).sum(axis=1)
        annual_return = float((1 + portfolio_returns.mean()) ** 252 - 1) if not portfolio_returns.empty else 0.0
        annual_volatility = float(portfolio_returns.std(ddof=0) * np.sqrt(252)) if portfolio_returns.std(ddof=0) > 0 else 0.0
        sharpe = float(annual_return / annual_volatility) if annual_volatility > 0 else 0.0
        return {
            "expected_annual_return": annual_return,
            "annual_volatility": annual_volatility,
            "sharpe_ratio": sharpe,
        }

    @staticmethod
    def _cap_weights(weights: dict[str, float], max_weight: float, special_max_weights: dict[str, float]) -> dict[str, float]:
        """只做降杠杆式截断，剩余部分保留为现金，不强行再分配。"""
        capped = {}
        for symbol, weight in weights.items():
            symbol_max_weight = special_max_weights.get(symbol, max_weight)
            if weight <= 0:
                capped[symbol] = 0.0
            else:
                capped[symbol] = min(float(weight), symbol_max_weight)
        return capped
