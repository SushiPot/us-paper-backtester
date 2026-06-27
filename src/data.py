from __future__ import annotations

import time

import pandas as pd
import requests
import yfinance as yf

from .config import BacktestConfig


class MarketDataLoader:
    """使用 yfinance 下载历史日线数据，失败时自动重试。"""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)

    def download_symbol(self, symbol: str, allow_network: bool = True) -> pd.DataFrame:
        cached = self._load_cache(symbol)
        if cached is not None:
            return cached
        if not allow_network:
            stale = self._load_cache(symbol, allow_stale=True)
            if stale is not None:
                print(f"{symbol} 使用过期缓存，本次运行不再新增网络下载")
                return stale
            raise RuntimeError(f"{symbol} 未缓存，且本次运行网络下载预算已用完")

        last_error: Exception | None = None

        try:
            data = yf.download(
                symbol,
                start=self.config.start_date,
                end=self.config.end_date,
                auto_adjust=True,
                progress=False,
                threads=False,
                timeout=self.config.yfinance_timeout_seconds,
            )
            if data.empty:
                raise ValueError(f"{symbol} 没有下载到数据")

            data = self._normalize_columns(data)
            data = data[["open", "high", "low", "close", "volume"]].dropna()
            data.index = pd.to_datetime(data.index).tz_localize(None)
            self._save_cache(symbol, data)
            return data
        except Exception as exc:
            last_error = exc
            print(f"{symbol} yfinance 下载失败: {exc}")

        print(f"{symbol} 切换到 Yahoo Chart 备用接口")
        try:
            data = self._download_from_yahoo_chart(symbol)
            self._save_cache(symbol, data)
            return data
        except Exception as exc:
            stale = self._load_cache(symbol, allow_stale=True)
            if stale is not None:
                print(f"{symbol} 下载失败，降级使用本地过期缓存")
                return stale
            raise RuntimeError(f"{symbol} 数据下载失败，已达到最大重试次数") from exc

    def download_all(self) -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        downloads_used = 0
        max_downloads = int(getattr(self.config, "max_new_symbol_downloads_per_run", 25))
        skipped_due_budget: list[str] = []
        for symbol in self.config.symbols:
            fresh_cache_exists = self._fresh_cache_exists(symbol)
            allow_network = max_downloads < 0 or fresh_cache_exists or downloads_used < max_downloads
            if not allow_network and not self._cache_path(symbol).exists():
                skipped_due_budget.append(symbol)
                frames[symbol] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                continue
            try:
                frames[symbol] = self.download_symbol(symbol, allow_network=allow_network)
                if not fresh_cache_exists and allow_network:
                    downloads_used += 1
            except Exception as exc:
                print(f"{symbol} 数据不可用，跳过该标的: {type(exc).__name__}: {exc}")
                frames[symbol] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if skipped_due_budget:
            preview = ", ".join(skipped_due_budget[:10])
            suffix = "..." if len(skipped_due_budget) > 10 else ""
            print(
                f"[INFO] 本次跳过 {len(skipped_due_budget)} 个未缓存标的，原因是新增下载预算已用完: {preview}{suffix}",
                flush=True,
            )
        return frames

    @staticmethod
    def _normalize_columns(data: pd.DataFrame) -> pd.DataFrame:
        """兼容 yfinance 单标的返回的普通列和 MultiIndex 列。"""
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        renamed = {column: str(column).strip().lower().replace(" ", "_") for column in data.columns}
        return data.rename(columns=renamed)

    def _download_from_yahoo_chart(self, symbol: str) -> pd.DataFrame:
        """yfinance 不可用时，直接调用 Yahoo Chart 历史接口作为备用。"""
        start = int(pd.Timestamp(self.config.start_date, tz="UTC").timestamp())
        if self.config.end_date:
            end = int(pd.Timestamp(self.config.end_date, tz="UTC").timestamp())
        else:
            end = int(pd.Timestamp.utcnow().timestamp())

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {
            "period1": start,
            "period2": end,
            "interval": "1d",
            "events": "history",
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
        }

        last_error: Exception | None = None
        for attempt in range(1, self.config.retry_count + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                payload = response.json()
                result = payload["chart"]["result"][0]
                timestamps = result["timestamp"]
                quote = result["indicators"]["quote"][0]

                frame = pd.DataFrame(
                    {
                        "open": quote["open"],
                        "high": quote["high"],
                        "low": quote["low"],
                        "close": quote["close"],
                        "volume": quote["volume"],
                    },
                    index=pd.to_datetime(timestamps, unit="s").tz_localize("UTC").tz_convert(None).normalize(),
                )
                frame = frame.dropna()
                if frame.empty:
                    raise ValueError(f"{symbol} Yahoo Chart 备用接口没有返回有效数据")
                return frame
            except Exception as exc:
                last_error = exc
                print(f"{symbol} Yahoo Chart 备用接口失败，第 {attempt} 次重试: {exc}")
                time.sleep(self.config.retry_wait_seconds)

        raise RuntimeError(f"{symbol} Yahoo Chart 备用接口失败") from last_error

    def _cache_path(self, symbol: str):
        return self.config.cache_dir / f"{symbol}.csv"

    def _load_cache(self, symbol: str, allow_stale: bool = False) -> pd.DataFrame | None:
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        if self.config.end_date is None and self._cache_is_stale(path) and not allow_stale:
            print(f"{symbol} 本地缓存超过 {self.config.cache_max_age_hours:.1f} 小时，重新下载行情")
            return None
        data = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        data.index = pd.to_datetime(data.index)
        return data[["open", "high", "low", "close", "volume"]]

    def _fresh_cache_exists(self, symbol: str) -> bool:
        path = self._cache_path(symbol)
        if not path.exists():
            return False
        return self.config.end_date is not None or not self._cache_is_stale(path)

    def _cache_is_stale(self, path) -> bool:
        max_age_seconds = self.config.cache_max_age_hours * 60 * 60
        if max_age_seconds <= 0:
            return True
        return (time.time() - path.stat().st_mtime) > max_age_seconds

    def _save_cache(self, symbol: str, data: pd.DataFrame) -> None:
        path = self._cache_path(symbol)
        output = data.copy()
        output.insert(0, "date", output.index)
        output.to_csv(path, index=False)
