"""Exercise installer settings without registering or changing any Windows task."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
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
    def test_installer_retries_only_daily_mode_and_preserves_runtime_safety(self):
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
                self.assertEqual(settings["restart_count"], 0 if legacy else 1)
                if not legacy:
                    self.assertEqual(settings["restart_interval"], "PT1H")
                self.assertTrue(settings["start_when_available"])
                self.assertEqual(settings["multiple_instances"], 2)
                self.assertEqual(settings["execution_limit"], "PT3H")
                self.assertEqual(settings["days_interval"], 1)
                self.assertIn("-WindowStyle Hidden", settings["arguments"])
                self.assertIn("-NonInteractive", settings["arguments"])
                self.assertEqual("-LegacyPaper" in settings["arguments"], legacy)


if __name__ == "__main__":
    unittest.main()
