"""Separate, verified adjusted-price cache for prediction research."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd
import requests

from .config import DEFAULT_SYMBOLS, WATCH_ONLY_SYMBOLS
from .market_calendar import get_us_market_session, now_new_york


@dataclass(frozen=True)
class PredictionConfig:
    symbols: tuple[str, ...] = field(default_factory=lambda: tuple(s for s in DEFAULT_SYMBOLS if s not in WATCH_ONLY_SYMBOLS))
    start: str = "2000-01-01"
    train_end: str = "2021-12-31"
    validation_end: str = "2023-12-31"
    test_end: str = "2025-12-31"
    horizon: int = 5
    cost_bps: float = 20.0
    top_k: int = 5
    min_symbols: int = 10
    min_train_dates: int = 756
    min_eval_dates: int = 126
    seed: int = 42
    cache_dir: Path = Path("data_cache/prediction")
    output_dir: Path = Path("outputs/prediction")
    request_interval: float = 3.0

    def __post_init__(self):
        if not (pd.Timestamp(self.start) < pd.Timestamp(self.train_end) < pd.Timestamp(self.validation_end) < pd.Timestamp(self.test_end)):
            raise ValueError("Require start < train_end < validation_end < test_end")
        if self.horizon < 1 or self.top_k < 1 or self.cost_bps < 0:
            raise ValueError("Invalid horizon, position count, or cost")
        if any(not re.fullmatch(r"[A-Z0-9.^-]{1,20}", symbol) for symbol in self.symbols):
            raise ValueError("Invalid symbol")


def completed_session() -> pd.Timestamp:
    now = now_new_york()
    for offset in range(15):
        session = get_us_market_session(now - timedelta(days=offset))
        if session.market_close and now >= session.market_close + timedelta(minutes=30):
            return pd.Timestamp(session.trading_day)
    raise RuntimeError("Cannot determine latest completed trading session")


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def validate_prices(frame: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
    columns = ["open", "high", "low", "close", "volume"]
    if frame.empty or not set(columns).issubset(frame.columns):
        raise ValueError("Missing OHLCV data")
    data = frame[columns].apply(pd.to_numeric, errors="raise").copy()
    data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
    if data.index.hasnans or data.index.has_duplicates or not data.index.is_monotonic_increasing:
        raise ValueError("Invalid, duplicate or unordered dates")
    if not np.isfinite(data.to_numpy()).all():
        raise ValueError("Non-finite OHLCV data")
    prices = data[["open", "high", "low", "close"]]
    if (prices <= 0).any().any() or (data.volume < 0).any():
        raise ValueError("Nonpositive price or negative volume")
    if ((data.high + 1e-7 < prices.max(axis=1)) | (data.low - 1e-7 > prices.min(axis=1))).any():
        raise ValueError("Inconsistent OHLC range")
    changes = data.close.pct_change(fill_method=None)
    extreme = changes.loc[changes.abs() > 0.8]
    reviews_path = Path(__file__).resolve().parents[1] / "config" / "prediction_price_reviews.json"
    reviews = json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.exists() else []
    for date, change in extreme.items():
        reviewed = any(item["symbol"] == symbol and item["date"] == str(date.date())
                       and abs(change - item["expected_return"]) <= item["tolerance"] for item in reviews)
        if not reviewed:
            raise ValueError(f"Extreme daily move requires manual split/data review: {date.date()} {change:.6f}")
    return data


def parse_chart(payload: dict, as_of: pd.Timestamp, symbol: str | None = None) -> pd.DataFrame:
    results = payload.get("chart", {}).get("result")
    if not results:
        raise ValueError("Yahoo chart has no result")
    result = results[0]
    indicators = result["indicators"]
    quote = indicators["quote"][0]
    adjusted = indicators.get("adjclose", [{}])[0].get("adjclose")
    if adjusted is None:
        raise ValueError("Adjusted close missing; raw prices cannot enter prediction cache")
    frame = pd.DataFrame({key: quote[key] for key in ("open", "high", "low", "close", "volume")},
                         index=pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize())
    frame["adjusted"] = adjusted
    frame = frame.loc[frame.index <= as_of].dropna()
    ratio = frame.adjusted / frame.close
    frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]].mul(ratio, axis=0)
    return validate_prices(frame.drop(columns="adjusted"), symbol)


class PredictionDataStore:
    def __init__(self, config: PredictionConfig):
        self.config = config
        config.cache_dir.mkdir(parents=True, exist_ok=True)

    def read(self, symbol: str) -> tuple[pd.DataFrame, dict]:
        path = self.config.cache_dir / f"{symbol}.csv"
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if meta.get("schema") != 1 or meta.get("price_basis") != "dividend_split_adjusted":
            raise ValueError("Unverified price adjustment schema")
        if meta.get("symbol") != symbol or meta.get("sha256") != file_hash(path):
            raise ValueError("Cache checksum or symbol mismatch")
        frame = validate_prices(pd.read_csv(path, index_col="date", parse_dates=["date"]), symbol)
        return frame, meta

    def load(self, *, refresh: bool = False, max_downloads: int = 60, as_of=None) -> tuple[dict, pd.DataFrame]:
        as_of = pd.Timestamp(as_of) if as_of is not None else completed_session()
        frames, inventory = {}, []
        symbols = list(dict.fromkeys(("SPY",) + self.config.symbols))
        downloads, blocked, last_request = 0, "", 0.0
        with requests.Session() as session:
            for index, symbol in enumerate(symbols, 1):
                frame, meta, reason = None, {}, ""
                try:
                    frame, meta = self.read(symbol)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                current = (frame is not None and frame.index.max() >= as_of and
                           str(meta.get("requested_start", "9999")) <= self.config.start)
                if refresh and not current and not blocked and downloads < max_downloads:
                    downloads += 1
                    print(f"[DATA {index}/{len(symbols)}] {symbol}: fetching adjusted history", flush=True)
                    for attempt in range(2):
                        time.sleep(max(0, self.config.request_interval - (time.monotonic() - last_request)))
                        try:
                            response = session.get(
                                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                                params={"period1": int(pd.Timestamp(self.config.start, tz="UTC").timestamp()),
                                        "period2": int((as_of.tz_localize("UTC") + pd.Timedelta(days=1)).timestamp()),
                                        "interval": "1d", "events": "div,splits"},
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
                            )
                            if response.status_code in (401, 403, 429):
                                blocked = f"Yahoo HTTP {response.status_code}; further requests stopped"
                            response.raise_for_status()
                            downloaded = parse_chart(response.json(), as_of, symbol)
                            path = self.config.cache_dir / f"{symbol}.csv"
                            tmp = path.with_suffix(".csv.tmp")
                            downloaded.to_csv(tmp, index_label="date")
                            tmp.replace(path)
                            meta = {"schema": 1, "symbol": symbol, "source": "yahoo_chart",
                                    "price_basis": "dividend_split_adjusted", "requested_start": self.config.start,
                                    "fetched_at": pd.Timestamp.now("UTC").isoformat(), "sha256": file_hash(path)}
                            write_json(path.with_suffix(".json"), meta)
                            frame, reason = downloaded, ""
                            break
                        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                            reason = f"{type(exc).__name__}: {exc}"
                            if blocked:
                                break
                            if attempt == 0:
                                time.sleep(5)
                        finally:
                            last_request = time.monotonic()
                if frame is not None:
                    frame = frame.loc[(frame.index >= pd.Timestamp(self.config.start)) & (frame.index <= as_of)]
                    if not frame.empty:
                        frames[symbol] = frame
                valid = symbol in frames
                coverage = str(meta.get("requested_start", "9999")) <= self.config.start
                status = "MISSING" if not valid else "CURRENT" if frames[symbol].index.max() == as_of and coverage else "STALE"
                if valid and not coverage:
                    reason = reason or "Cache was requested with a shorter historical window"
                inventory.append({"symbol": symbol, "status": status, "rows": len(frame) if frame is not None else 0,
                                  "start": str(frame.index.min().date()) if valid else "",
                                  "end": str(frame.index.max().date()) if valid else "",
                                  "sha256": meta.get("sha256", ""), "reason": reason or (blocked if not current else "")})
                print(f"[DATA] {symbol}: {status}", flush=True)
        return frames, pd.DataFrame(inventory)
