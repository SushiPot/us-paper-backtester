from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, time as dt_time
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from src.agents.manager import AgentMode
from src.cache_warmup import MarketCacheWarmup
from src.config import BacktestConfig, LocalPaperConfig
from src.daemon import AgentDaemon, DaemonConfig
from src.data import MarketDataLoader
from src.market_calendar import MarketSession, NEW_YORK_TZ


def sample_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [10.0, 10.5],
            "high": [11.0, 11.5],
            "low": [9.5, 10.0],
            "close": [10.8, 11.2],
            "volume": [1000, 1200],
        },
        index=pd.to_datetime(["2026-06-26", "2026-06-29"]),
    )


class DummyStore:
    def append_frame(self, *_args, **_kwargs) -> None:
        return None

    def append_generic_frame(self, *_args, **_kwargs) -> None:
        return None


class MarketDataRuntimeTests(unittest.TestCase):
    def test_default_market_data_source_prefers_yahoo_chart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MARKET_DATA_PRIMARY_SOURCE", None)
            config = BacktestConfig(cache_dir=Path(tmp), retry_count=1, retry_wait_seconds=0)
            loader = MarketDataLoader(config)

            self.assertEqual(config.market_data_primary_source, "yahoo_chart")
            self.assertTrue(loader._prefer_yahoo_chart())

    def test_yahoo_chart_primary_does_not_call_yfinance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loader = MarketDataLoader(
                BacktestConfig(
                    cache_dir=Path(tmp),
                    market_data_primary_source="yahoo_chart",
                    retry_count=1,
                    retry_wait_seconds=0,
                    market_data_request_interval_seconds=0,
                )
            )

            with (
                patch("src.data.yf.download", side_effect=AssertionError("yfinance should not be called")) as yf_download,
                patch.object(loader, "_download_from_yahoo_chart", return_value=sample_ohlcv()) as yahoo_chart,
            ):
                frame = loader.download_symbol("AAA")

            self.assertEqual(len(frame), 2)
            yf_download.assert_not_called()
            yahoo_chart.assert_called_once_with("AAA")
            self.assertTrue((Path(tmp) / "AAA.csv").exists())

    def test_yfinance_rate_limit_skips_yfinance_for_rest_of_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loader = MarketDataLoader(
                BacktestConfig(
                    cache_dir=Path(tmp),
                    market_data_primary_source="yfinance",
                    retry_count=1,
                    retry_wait_seconds=0,
                    market_data_request_interval_seconds=0,
                )
            )

            with (
                patch("src.data.yf.download", side_effect=RuntimeError("Too Many Requests. Rate limited.")) as yf_download,
                patch.object(loader, "_download_from_yahoo_chart", side_effect=[sample_ohlcv(), sample_ohlcv()]) as yahoo_chart,
            ):
                first = loader.download_symbol("AAA")
                second = loader.download_symbol("BBB")

            self.assertEqual(len(first), 2)
            self.assertEqual(len(second), 2)
            self.assertEqual(yf_download.call_count, 1)
            self.assertEqual(yahoo_chart.call_count, 2)
            self.assertTrue(loader._skip_yfinance_for_run)


class CacheWarmupRuntimeTests(unittest.TestCase):
    def test_zero_limit_checks_cache_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("src.cache_warmup.get_store", return_value=DummyStore()):
            config = LocalPaperConfig(
                symbols=["AAA", "BBB"],
                required_symbols=["AAA"],
                watch_only_symbols=[],
                output_dir=Path(tmp),
                cache_warmup_symbols_per_run=5,
                market_data_request_interval_seconds=0,
            )
            warmup = MarketCacheWarmup(config, output_dir=Path(tmp), max_symbols=0)
            warmup.loader.download_symbol = Mock(side_effect=AssertionError("warmup should not download at limit 0"))

            result = warmup.run()

            self.assertEqual(result.status, "WARN")
            self.assertIn("下载限制为0", result.message)
            summary = result.summary.iloc[0]
            self.assertEqual(int(summary["missing"]), 2)
            self.assertEqual(int(summary["selected"]), 0)
            warmup.loader.download_symbol.assert_not_called()
            self.assertTrue((Path(tmp) / "cache_warmup_summary.csv").exists())


class DaemonRuntimeTests(unittest.TestCase):
    def test_run_once_idles_when_no_jobs_are_due(self) -> None:
        fixed_now = datetime(2026, 6, 30, 10, 0, tzinfo=NEW_YORK_TZ)

        def fake_session(moment: datetime | None = None) -> MarketSession:
            current = (moment or fixed_now).astimezone(NEW_YORK_TZ)
            market_open = datetime.combine(current.date(), dt_time(9, 30), tzinfo=NEW_YORK_TZ)
            market_close = datetime.combine(current.date(), dt_time(16, 0), tzinfo=NEW_YORK_TZ)
            return MarketSession(
                trading_day=current.date(),
                is_trading_day=True,
                is_regular_hours=market_open <= current <= market_close,
                market_open=market_open,
                market_close=market_close,
                source="test",
            )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "outputs"
            log_dir = Path(tmp) / "logs"
            output_dir.mkdir()
            (output_dir / "agent_status.json").write_text(
                json.dumps({"status": "IDLE", "jobs": {"daily_risk_check": {"last_run_key": "2026-06-30"}}}),
                encoding="utf-8",
            )
            daemon = AgentDaemon(
                DaemonConfig(
                    mode=AgentMode.ONLINE,
                    output_dir=output_dir,
                    log_dir=log_dir,
                    enable_online_scan=False,
                    enable_weekly_research=False,
                    enable_cache_warmup=False,
                )
            )

            with patch("src.daemon.now_new_york", return_value=fixed_now), patch(
                "src.daemon.get_us_market_session", side_effect=fake_session
            ):
                results = daemon.run_once()

            self.assertEqual(results, [])
            state = json.loads((output_dir / "agent_status.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "IDLE")
            self.assertEqual(state["message"], "No jobs due")
            self.assertIn("[IDLE] No daemon jobs are due", (log_dir / "daemon.log").read_text(encoding="utf-8"))


class SelfUpdateRuntimeTests(unittest.TestCase):
    def test_self_update_help_imports_cleanly(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(project_root / "self_update_main.py"), "--help"],
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("safe daily self-update workflow", completed.stdout)


if __name__ == "__main__":
    unittest.main()
