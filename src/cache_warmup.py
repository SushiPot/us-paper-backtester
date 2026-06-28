from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import time

import pandas as pd

from .config import BacktestConfig, LocalPaperConfig
from .data import MarketDataLoader
from .database import get_store


@dataclass(frozen=True)
class CacheWarmupResult:
    """缓存预热汇总结果。"""

    status: str
    message: str
    summary: pd.DataFrame
    log: pd.DataFrame


class MarketCacheWarmup:
    """渐进式补齐 Yahoo/yfinance 行情缓存，不下单、不修改持仓。"""

    def __init__(
        self,
        config: LocalPaperConfig | None = None,
        output_dir: Path | None = None,
        max_symbols: int | None = None,
    ) -> None:
        self.config = config or LocalPaperConfig()
        self.output_dir = output_dir or self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_symbols = self.config.cache_warmup_symbols_per_run if max_symbols is None else int(max_symbols)
        self.data_config = BacktestConfig(
            symbols=self.config.symbols,
            required_symbols=self.config.required_symbols,
            watch_only_symbols=self.config.watch_only_symbols,
            start_date=self.config.historical_start_date,
            output_dir=self.output_dir,
            retry_count=self.config.retry_count,
            retry_wait_seconds=self.config.retry_wait_seconds,
            max_new_symbol_downloads_per_run=max(self.max_symbols, 0),
        )
        self.loader = MarketDataLoader(self.data_config)

    def run(self) -> CacheWarmupResult:
        """按核心优先、缺失优先的顺序补缓存。"""
        print("[START] MarketCacheWarmup.run 已进入", flush=True)
        inventory = self._inventory()
        selected = self._select_symbols(inventory)
        rows: list[dict[str, object]] = []

        if selected.empty:
            needs_refresh = inventory[inventory["cache_status"].isin(["MISSING", "STALE"])] if not inventory.empty else inventory
            if needs_refresh.empty:
                status = "OK"
                message = "所有目标股票缓存都存在且未过期"
            elif self.max_symbols == 0:
                status = "WARN"
                message = f"检查完成但本次下载限制为0，仍有 {len(needs_refresh)} 个缓存缺失或过期"
            else:
                status = "WARN"
                message = f"仍有 {len(needs_refresh)} 个缓存缺失或过期，但本次没有选中下载目标"
            summary = self._summary(inventory, selected, rows, status, message)
            self._save(summary, pd.DataFrame(rows))
            print(f"[{status}] {message}", flush=True)
            return CacheWarmupResult(status, message, summary, pd.DataFrame(rows))

        for item in selected.to_dict(orient="records"):
            symbol = str(item["symbol"])
            print(f"[CHECK] 缓存预热 {symbol}: {item['cache_status']}", flush=True)
            started_at = time()
            row = {
                "time": pd.Timestamp.now(),
                "symbol": symbol,
                "priority": item["priority"],
                "previous_status": item["cache_status"],
                "result_status": "UNKNOWN",
                "rows": 0,
                "latest_date": "",
                "cache_age_hours": "",
                "reason": "",
            }
            try:
                frame = self.loader.download_symbol(symbol, allow_network=True)
                rows_count = int(len(frame))
                latest_date = self._latest_date(frame)
                cache_path = self.loader._cache_path(symbol)
                modified = cache_path.exists() and cache_path.stat().st_mtime >= started_at - 1
                if rows_count <= 0:
                    row["result_status"] = "ERROR"
                    row["reason"] = "下载后数据为空"
                elif modified:
                    row["result_status"] = "DOWNLOADED"
                    row["reason"] = "缓存已刷新"
                else:
                    row["result_status"] = "STALE_FALLBACK"
                    row["reason"] = "联网失败或未刷新，使用了已有旧缓存"
                row["rows"] = rows_count
                row["latest_date"] = latest_date
                row["cache_age_hours"] = self._cache_age_hours(symbol)
            except Exception as exc:
                row["result_status"] = "ERROR"
                row["reason"] = f"{type(exc).__name__}: {exc}"
                print(f"[ERROR] {symbol} 缓存预热失败: {type(exc).__name__}: {exc}", flush=True)
            rows.append(row)

        log = pd.DataFrame(rows)
        errors = int((log["result_status"] == "ERROR").sum()) if not log.empty else 0
        stale_fallback = int((log["result_status"] == "STALE_FALLBACK").sum()) if not log.empty else 0
        downloaded = int((log["result_status"] == "DOWNLOADED").sum()) if not log.empty else 0
        if errors and downloaded == 0 and stale_fallback == 0:
            status = "ERROR"
        elif errors or stale_fallback:
            status = "WARN"
        else:
            status = "OK"
        message = f"selected={len(selected)} downloaded={downloaded} stale_fallback={stale_fallback} errors={errors}"
        final_inventory = self._inventory()
        summary = self._summary(final_inventory, selected, rows, status, message)
        self._save(summary, log)
        print(f"[END] MarketCacheWarmup.run {status}: {message}", flush=True)
        return CacheWarmupResult(status, message, summary, log)

    def _inventory(self) -> pd.DataFrame:
        required = set(self.config.required_symbols or [])
        rows = []
        for position, symbol in enumerate(self.config.symbols):
            cache_path = self.loader._cache_path(symbol)
            exists = cache_path.exists()
            stale = exists and self.loader._cache_is_stale(cache_path)
            if not exists:
                cache_status = "MISSING"
            elif stale:
                cache_status = "STALE"
            else:
                cache_status = "FRESH"
            rows.append(
                {
                    "symbol": symbol,
                    "position": position,
                    "is_required": symbol in required,
                    "cache_status": cache_status,
                    "cache_age_hours": self._cache_age_hours(symbol),
                }
            )
        return pd.DataFrame(rows)

    def _select_symbols(self, inventory: pd.DataFrame) -> pd.DataFrame:
        if inventory.empty:
            return inventory.head(0).copy()
        candidates = inventory[inventory["cache_status"].isin(["MISSING", "STALE"])].copy()
        if candidates.empty:
            return candidates

        priority_map = {
            (True, "MISSING"): 0,
            (True, "STALE"): 1,
            (False, "MISSING"): 2,
            (False, "STALE"): 3,
        }
        candidates["priority_rank"] = candidates.apply(
            lambda row: priority_map[(bool(row["is_required"]), str(row["cache_status"]))],
            axis=1,
        )
        candidates["priority"] = candidates["priority_rank"].map(
            {
                0: "REQUIRED_MISSING",
                1: "REQUIRED_STALE",
                2: "OPTIONAL_MISSING",
                3: "OPTIONAL_STALE",
            }
        )
        attempts = self._attempt_lookup()
        candidates["attempt_count"] = candidates["symbol"].map(lambda symbol: int(attempts.get(symbol, {}).get("attempt_count", 0)))
        candidates["last_attempt_at"] = candidates["symbol"].map(lambda symbol: str(attempts.get(symbol, {}).get("last_attempt_at", "")))
        candidates = candidates.sort_values(["priority_rank", "attempt_count", "last_attempt_at", "position"]).reset_index(drop=True)
        queue = candidates.drop(columns=["priority_rank"], errors="ignore").copy()
        queue["queue_rank"] = queue.index + 1
        queue.to_csv(self.output_dir / "cache_warmup_queue.csv", index=False, encoding="utf-8-sig")
        if self.max_symbols == 0:
            return candidates.head(0).copy()
        if self.max_symbols < 0:
            return candidates
        return candidates.head(self.max_symbols).copy()

    def _attempt_lookup(self) -> dict[str, dict[str, object]]:
        path = self.output_dir / "cache_warmup_log.csv"
        if not path.exists() or path.stat().st_size == 0:
            return {}
        try:
            log = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return {}
        if log.empty or "symbol" not in log.columns:
            return {}
        lookup: dict[str, dict[str, object]] = {}
        for symbol, group in log.groupby("symbol"):
            lookup[str(symbol)] = {
                "attempt_count": int(len(group)),
                "last_attempt_at": str(group.iloc[-1].get("time", "")),
            }
        return lookup

    def _summary(
        self,
        inventory: pd.DataFrame,
        selected: pd.DataFrame,
        rows: list[dict[str, object]],
        status: str,
        message: str,
    ) -> pd.DataFrame:
        log = pd.DataFrame(rows)
        result_counts = log["result_status"].value_counts().to_dict() if not log.empty else {}
        status_counts = inventory["cache_status"].value_counts().to_dict() if not inventory.empty else {}
        return pd.DataFrame(
            [
                {
                    "time": pd.Timestamp.now(),
                    "status": status,
                    "message": message,
                    "total_symbols": int(len(inventory)),
                    "fresh": int(status_counts.get("FRESH", 0)),
                    "stale": int(status_counts.get("STALE", 0)),
                    "missing": int(status_counts.get("MISSING", 0)),
                    "selected": int(len(selected)),
                    "downloaded": int(result_counts.get("DOWNLOADED", 0)),
                    "stale_fallback": int(result_counts.get("STALE_FALLBACK", 0)),
                    "failed": int(result_counts.get("ERROR", 0)),
                    "limit": int(self.max_symbols),
                }
            ]
        )

    def _save(self, summary: pd.DataFrame, log: pd.DataFrame) -> None:
        summary.to_csv(self.output_dir / "cache_warmup_summary.csv", index=False, encoding="utf-8-sig")
        if not log.empty:
            path = self.output_dir / "cache_warmup_log.csv"
            header = not path.exists() or path.stat().st_size == 0
            log.to_csv(path, mode="a", header=header, index=False, encoding="utf-8-sig")
            get_store().append_generic_frame("cache_warmup_log", "cache_warmup_log.csv", log)
        get_store().append_generic_frame("cache_warmup_summary", "cache_warmup_summary.csv", summary)

    def _cache_age_hours(self, symbol: str) -> float | str:
        path = self.loader._cache_path(symbol)
        if not path.exists():
            return ""
        return round((time() - path.stat().st_mtime) / 3600, 2)

    @staticmethod
    def _latest_date(frame: pd.DataFrame) -> str:
        if frame.empty:
            return ""
        return pd.Timestamp(frame.index.max()).date().isoformat()
