from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from src.config import LocalPaperConfig
from src.signal_evaluation import SignalEvaluationAnalyzer


class SignalStorageTests(unittest.TestCase):
    def test_repeated_analysis_keeps_detail_snapshot_and_only_archives_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            analyzer = SignalEvaluationAnalyzer(LocalPaperConfig(signal_eval_horizons=[5]), output)
            store = Mock()

            def evaluate(_data, strategy, horizon, _lookup):
                return [{
                    "strategy_name": strategy, "horizon_days": horizon,
                    "predicted_positive": True, "actual_positive": True, "future_return": 0.05,
                }]

            with (
                patch.object(analyzer, "_build_historical_relative_strength", return_value={}),
                patch.object(analyzer, "_evaluate_strategy", side_effect=evaluate),
                patch("src.signal_evaluation.get_store", return_value=store),
            ):
                analyzer.run({})
                analyzer.run({})

            detail = pd.read_csv(output / "signal_evaluation.csv")
            summary = pd.read_csv(output / "signal_evaluation_summary.csv")
            self.assertEqual(len(detail), 4)
            self.assertEqual(len(summary), 4)
            self.assertTrue((summary["precision"] == 1.0).all())
            self.assertTrue((output / "signal_evaluation_report.md").exists())
            self.assertEqual(store.append_generic_frame.call_count, 2)
            for call in store.append_generic_frame.call_args_list:
                self.assertEqual(call.args[:2], ("signal_evaluation_summary", "signal_evaluation_summary.csv"))
                pd.testing.assert_frame_equal(call.args[2].drop(columns="time").reset_index(drop=True),
                                              summary.drop(columns="time"))


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Requires Windows PowerShell")
class ScheduledRunnerTests(unittest.TestCase):
    def test_stderr_preserves_output_and_python_exit_code(self) -> None:
        project = Path(__file__).resolve().parents[1]
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                scripts = root / "scripts"
                scripts.mkdir()
                runner = scripts / "run_scheduled_self_update.ps1"
                shutil.copyfile(project / "scripts" / runner.name, runner)
                executable = sys.executable.replace("'", "''")
                (scripts / "python_env.ps1").write_text(
                    f"function Resolve-ProjectPython {{ return '{executable}' }}\n", encoding="utf-8"
                )
                (root / "self_update_main.py").write_text(
                    "import sys\n"
                    "print('before-stderr', flush=True)\n"
                    "print('stderr-diagnostic', file=sys.stderr, flush=True)\n"
                    "print('after-stderr', flush=True)\n"
                    f"sys.exit({exit_code})\n", encoding="utf-8"
                )
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner)],
                    capture_output=True, timeout=45,
                )
                self.assertEqual(result.returncode, exit_code, repr(result.stderr))
                logs = list((root / "logs").glob("scheduled_self_update_*.log"))
                self.assertEqual(len(logs), 1)
                content = logs[0].read_bytes()
                text = content.decode("utf-16" if content.startswith(b"\xff\xfe") else "utf-8-sig")
                for marker in ("before-stderr", "stderr-diagnostic", "after-stderr"):
                    self.assertIn(marker, text)
                expected = "scheduled self update completed" if exit_code == 0 else "failed with exit code 7"
                self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
