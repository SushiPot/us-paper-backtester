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
        self._last_network_request_finished_at = 0.0
        self._skip_yfinance_for_run = False

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

        if self._prefer_yahoo_chart():
            print(f"{symbol} 使用 Yahoo Chart 行情接口", flush=True)
            try:
                data = self._download_from_yahoo_chart(symbol)
                self._save_cache(symbol, data)
                return data
            except Exception as exc:
                last_error = exc
                stale = self._load_cache(symbol, allow_stale=True)
                if stale is not None:
                    print(f"{symbol} Yahoo Chart 下载失败，降级使用本地过期缓存")
                    return stale
                print(f"{symbol} Yahoo Chart 下载失败，最后尝试 yfinance: {type(exc).__name__}: {exc}", flush=True)

        if self._skip_yfinance_for_run:
            print(f"{symbol} 本轮已检测到 yfinance 限流，直接使用 Yahoo Chart 备用接口", flush=True)
        else:
            for attempt in range(1, self.config.retry_count + 1):
                try:
                    self._wait_before_network_request(symbol, "yfinance")
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
                    finally:
                        self._mark_network_request_finished()
                    if data.empty:
                        last_error = ValueError(f"{symbol} 没有下载到数据")
                        self._skip_yfinance_for_run = True
                        print(f"{symbol} yfinance 返回空数据，本轮剩余标的直接切换备用接口", flush=True)
                        break

                    data = self._normalize_columns(data)
                    data = data[["open", "high", "low", "close", "volume"]].dropna()
                    data.index = pd.to_datetime(data.index).tz_localize(None)
                    self._save_cache(symbol, data)
                    return data
                except Exception as exc:
                    last_error = exc
                    print(f"{symbol} yfinance 下载失败，第 {attempt} 次: {exc}")
                    if self._is_rate_limit_error(exc):
                        self._skip_yfinance_for_run = True
                        print(f"{symbol} yfinance 触发限流，本轮剩余标的直接切换备用接口", flush=True)
                        break
                    if attempt < self.config.retry_count:
                        self._sleep_after_failure(attempt)

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
        max_downloads = int(getattr(self.config, "max_new_symbol_downloads_per_run", 10))
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
                self._wait_before_network_request(symbol, "Yahoo Chart")
                try:
                    response = requests.get(url, params=params, headers=headers, timeout=30)
                finally:
                    self._mark_network_request_finished()
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
                if self._is_rate_limit_error(exc):
                    print(f"{symbol} Yahoo Chart 触发限流，延长等待后再试", flush=True)
                self._sleep_after_failure(attempt)

        raise RuntimeError(f"{symbol} Yahoo Chart 备用接口失败") from last_error

    def _prefer_yahoo_chart(self) -> bool:
        source = str(getattr(self.config, "market_data_primary_source", "yahoo_chart")).strip().lower()
        return source not in {"yfinance", "yf"}

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return "ratelimit" in text or "rate limit" in text or "too many requests" in text or "429" in text

    def _wait_before_network_request(self, symbol: str, source: str) -> None:
        interval = max(float(getattr(self.config, "market_data_request_interval_seconds", 0.0)), 0.0)
        if interval <= 0:
            return

        elapsed = time.monotonic() - self._last_network_request_finished_at
        wait_seconds = interval - elapsed
        if wait_seconds > 0:
            print(f"{symbol} {source} 请求限速，等待 {wait_seconds:.1f} 秒", flush=True)
            time.sleep(wait_seconds)

    def _mark_network_request_finished(self) -> None:
        self._last_network_request_finished_at = time.monotonic()

    def _sleep_after_failure(self, attempt: int) -> None:
        base_wait = max(float(getattr(self.config, "retry_wait_seconds", 1.0)), 0.0)
        wait_seconds = base_wait * attempt
        if wait_seconds > 0:
            time.sleep(wait_seconds)

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
