from __future__ import annotations

import time

import pandas as pd
import requests
import yfinance as yf

from .config import BacktestConfig


class MarketDataLoader:
    """?? yfinance ?????????????????"""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)

    def download_symbol(self, symbol: str) -> pd.DataFrame:
        cached = self._load_cache(symbol)
        if cached is not None:
            return cached

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
                raise ValueError(f"{symbol} ???????")

            data = self._normalize_columns(data)
            data = data[["open", "high", "low", "close", "volume"]].dropna()
            data.index = pd.to_datetime(data.index).tz_localize(None)
            self._save_cache(symbol, data)
            return data
        except Exception as exc:
            last_error = exc
            print(f"{symbol} yfinance ????: {exc}")

        print(f"{symbol} ??? Yahoo Chart ????")
        try:
            data = self._download_from_yahoo_chart(symbol)
            self._save_cache(symbol, data)
            return data
        except Exception as exc:
            raise RuntimeError(f"{symbol} ????????????????") from exc

    def download_all(self) -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        for symbol in self.config.symbols:
            try:
                frames[symbol] = self.download_symbol(symbol)
            except Exception as exc:
                print(f"{symbol} ???????????: {type(exc).__name__}: {exc}")
                frames[symbol] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return frames

    @staticmethod
    def _normalize_columns(data: pd.DataFrame) -> pd.DataFrame:
        """?? yfinance ?????????? MultiIndex ??"""
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        renamed = {column: str(column).strip().lower().replace(" ", "_") for column in data.columns}
        return data.rename(columns=renamed)

    def _download_from_yahoo_chart(self, symbol: str) -> pd.DataFrame:
        """yfinance ????????? Yahoo Chart ?????????"""
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
                    raise ValueError(f"{symbol} Yahoo Chart ????????????")
                return frame
            except Exception as exc:
                last_error = exc
                print(f"{symbol} Yahoo Chart ???????? {attempt} ???: {exc}")
                time.sleep(self.config.retry_wait_seconds)

        raise RuntimeError(f"{symbol} Yahoo Chart ??????") from last_error

    def _cache_path(self, symbol: str):
        return self.config.cache_dir / f"{symbol}.csv"

    def _load_cache(self, symbol: str) -> pd.DataFrame | None:
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        if self.config.end_date is None and self._cache_is_stale(path):
            print(f"{symbol} ?????? {self.config.cache_max_age_hours:.1f} ?????????")
            return None
        data = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        data.index = pd.to_datetime(data.index)
        return data[["open", "high", "low", "close", "volume"]]

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
