"""Exercise installer settings without registering or changing any Windows task."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.prediction_data import PredictionConfig, PredictionDataStore, write_json


class RestartCooldownTests(unittest.TestCase):
    def test_restarted_history_and_quote_loaders_honor_remaining_server_cooldown(self):
        with tempfile.TemporaryDirectory() as temp:
            config = PredictionConfig(symbols=("AAA",), cache_dir=Path(temp), request_interval=0)
            state = config.cache_dir / "network_state.json"
            # An hourly restart may occur while a longer server Retry-After is still active.
            write_json(state, {"reason": "Yahoo HTTP 429; server cooldown still active",
                               "until": (pd.Timestamp.now("UTC") + pd.Timedelta(hours=1)).isoformat()})
            original = state.read_bytes()
            with patch("src.prediction_data.requests.Session") as session:
                get = session.return_value.__enter__.return_value.get
                get.side_effect = AssertionError("Restart must not bypass cooldown")
                loader = PredictionDataStore(config)
                _, inventory = loader.load(refresh=True, as_of="2026-10-27")
                quotes = PredictionDataStore(config).quotes(["SPY", "AAA"], refresh=True)
                get.assert_not_called()
            self.assertIn("cooldown still active", loader.blocked_reason)
            self.assertTrue((inventory.status == "MISSING").all())
            self.assertTrue(quotes.error.str.contains("cooldown still active").all())
            self.assertEqual(state.read_bytes(), original)


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Requires Windows PowerShell")
class ScheduledRecoveryTests(unittest.TestCase):
    def test_installer_leaves_recovery_to_runner_and_preserves_runtime_safety(self):
        installer = Path(__file__).resolve().parents[1] / "scripts/install_daily_self_update_task.ps1"
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                script = r'''
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks
$global:CapturedCalls = 0
function Register-ScheduledTask {
    param($TaskName, $Action, $Trigger, $Settings, $Description, [switch]$Force)
    $global:CapturedCalls += 1
    $result = @{
        restart_count = $Settings.RestartCount
        restart_interval = $Settings.RestartInterval
        start_when_available = $Settings.StartWhenAvailable
        multiple_instances = [int]$Settings.MultipleInstances
        execution_limit = $Settings.ExecutionTimeLimit
        arguments = $Action.Arguments
        days_interval = $Trigger.DaysInterval
    }
    Write-Output ('CAPTURE:' + ($result | ConvertTo-Json -Compress))
}
if ((Get-Command Register-ScheduledTask).CommandType -ne 'Function') {
    throw 'Registration stub is not active; refusing to execute installer'
}
'''
                script += f"& '{str(installer).replace(chr(39), chr(39) * 2)}' -TaskName 'ReadOnly Installer Test'"
                if legacy:
                    script += " -LegacyPaper"
                script += "\nif ($global:CapturedCalls -ne 1) { throw 'Installer did not use the registration stub' }\n"
                encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-EncodedCommand", encoded], capture_output=True, timeout=45,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(result.returncode, 0, repr(result.stderr))
                records = [json.loads(line[len("CAPTURE:"):]) for line in result.stdout.decode("utf-8", errors="replace").splitlines()
                           if line.startswith("CAPTURE:")]
                self.assertEqual(len(records), 1)
                settings = records[0]
                self.assertEqual(settings["restart_count"], 0)
                self.assertTrue(settings["start_when_available"])
                self.assertEqual(settings["multiple_instances"], 2)
                self.assertEqual(settings["execution_limit"], "PT3H")
                self.assertEqual(settings["days_interval"], 1)
                self.assertIn("-WindowStyle Hidden", settings["arguments"])
                self.assertIn("-NonInteractive", settings["arguments"])
                self.assertEqual("-LegacyPaper" in settings["arguments"], legacy)


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Requires Windows PowerShell")
class ScheduledRunnerTests(unittest.TestCase):
    def run_case(self, scenario, flags=()):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "scripts"
            scripts.mkdir()
            source = Path(__file__).resolve().parents[1] / "scripts/run_scheduled_self_update.ps1"
            runner = scripts / source.name
            shutil.copyfile(source, runner)
            (scripts / "python_env.ps1").write_text(
                "function Resolve-ProjectPython { return '" + sys.executable.replace("'", "''") + "' }\n",
                encoding="utf-8")
            (root / "scenario.txt").write_text(scenario, encoding="ascii")
            (root / "self_update_main.py").write_text('''
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
scenario = Path("scenario.txt").read_text()
calls = Path("calls.txt")
attempt = int(calls.read_text()) + 1 if calls.exists() else 1
calls.write_text(str(attempt))
now = datetime.now(timezone.utc)
status = {"status": "STALE_DATA", "data_ready": False, "updated_at": now.isoformat()}
network = {"reason": "synthetic cooldown", "until": (now + timedelta(hours=2)).isoformat()}
code = 1
if scenario == "success" or (scenario == "recovers" and attempt == 2):
    status.update(status="RESEARCH_ONLY", data_ready=True)
    code = 0
elif scenario == "gap":
    status.update(status="RESEARCH_ONLY", data_ready=True)
elif scenario == "error":
    status["status"] = "ERROR"
elif scenario == "old":
    status["updated_at"] = (now - timedelta(days=1)).isoformat()
elif scenario == "future":
    status["updated_at"] = (now + timedelta(days=1)).isoformat()
elif scenario == "expired":
    network["until"] = (now - timedelta(seconds=1)).isoformat()
elif scenario == "not_boolean":
    status["data_ready"] = "false"
directory = Path("outputs/prediction")
directory.mkdir(parents=True, exist_ok=True)
(directory / "status.json").write_text(json.dumps(status) if scenario != "malformed" else "bad json")
if scenario != "no_cooldown":
    directory = Path("data_cache/prediction")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "network_state.json").write_text(json.dumps(network))
print("Synthetic native stderr is not an exit status", file=sys.stderr)
sys.exit(code)
''', encoding="utf-8")
            wrapper = """
function Start-Sleep { param([int]$Seconds) Add-Content -LiteralPath 'sleep.txt' -Value $Seconds }
""" + f"& '{str(runner).replace(chr(39), chr(39) * 2)}' " + " ".join(flags)
            encoded = base64.b64encode(wrapper.encode("utf-16le")).decode("ascii")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                cwd=root, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertTrue((root / "calls.txt").exists(), repr(result.stderr))
            sleeps = (root / "sleep.txt").read_text().splitlines() if (root / "sleep.txt").exists() else []
            logs = list((root / "logs").glob("scheduled_self_update_*.log"))
            self.assertEqual(len(logs), 1)
            log = logs[0].read_text(encoding="utf-16")
            return result.returncode, int((root / "calls.txt").read_text()), sleeps, log

    def test_transient_failure_gets_one_delayed_recovery(self):
        code, calls, sleeps, log = self.run_case("recovers")
        self.assertEqual((code, calls, sleeps), (0, 2, ["3600"]))
        self.assertIn("[ATTEMPT] 2", log)
        self.assertIn("[OK]", log)

    def test_persistent_failure_is_bounded_and_returns_failure(self):
        code, calls, sleeps, log = self.run_case("persistent")
        self.assertEqual((code, calls, sleeps), (1, 2, ["3600"]))
        self.assertIn("[ERROR]", log)

    def test_success_with_native_stderr_does_not_retry(self):
        code, calls, sleeps, _ = self.run_case("success")
        self.assertEqual((code, calls, sleeps), (0, 1, []))

    def test_only_fresh_network_cooldown_failures_retry(self):
        for scenario in ("gap", "error", "old", "future", "expired", "not_boolean", "malformed", "no_cooldown"):
            with self.subTest(scenario=scenario):
                code, calls, sleeps, _ = self.run_case(scenario)
                self.assertEqual((code, calls, sleeps), (1, 1, []))

    def test_legacy_and_skipped_prediction_never_retry(self):
        for flag in ("-LegacyPaper", "-SkipPrediction"):
            with self.subTest(flag=flag):
                code, calls, sleeps, _ = self.run_case("persistent", (flag,))
                self.assertEqual((code, calls, sleeps), (1, 1, []))


if __name__ == "__main__":
    unittest.main()
