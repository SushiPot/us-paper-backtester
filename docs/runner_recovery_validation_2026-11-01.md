# Runner Recovery Validation: 2026-11-01

Times are Asia/Shanghai. This is an operational reliability change, not a model
experiment or evidence of improved prediction accuracy.

## Isolated Scheduler Probe

The October 30 provider failure and October 31 shadow-gap failure had no subsequent
retry logs despite a configured one-hour restart. On November 1, two temporary
one-time tasks ran a local script that exits 1 on its first invocation and 0 on a
second invocation. They had one restart configured at a one-minute interval,
hidden PowerShell, the current interactive account, and no market-data/model or
account access. Both fired at 14:55:04 and recorded their first attempt at 14:55:05.
Neither made a second attempt during the approximately 95 seconds observed after
its trigger; both retained exit code 1. Both temporary tasks were then removed
and their absence verified. No provider failure was deliberately induced.

The probes requested different unified-engine flags, but inspection of the saved
tasks showed **both actually used the unified engine**. Consequently this was not
a valid engine A/B comparison, and the log's `unified` field is the requested
value, not proof of the saved value. The result reproduces missing retry execution
within the observed window; it does not establish the scheduler's internal cause
or behavior beyond that window. No global Windows event logging or power policy
was changed.

Local probe artifacts are retained with `.log` suffixes and excluded from Git:

| Artifact | SHA-256 |
| --- | --- |
| `logs/retry_probe_20261101.ps1.log` | 121fcfea508d2275db68e78a077412f719f2b16c6ae6373600150022da873b4c |
| `logs/run_retry_probe_20261101.ps1.log` | 92bedecc780a2176f33837bbb365958514a518ce87177d6caa96eae5d0b0a65f |
| `logs/retry_probe_driver_20261101.log` | 28b34d4cb914ddd0e7e3723e8cb7eb9ce9be7588fbc912bd4c562cd3fe48edac |

## Bounded Runner Recovery

The runner now owns at most one recovery attempt, after 3600 seconds. It only
waits when the failed daily attempt produced fresh `STALE_DATA`, boolean false
readiness, and a still-active persisted network cooldown with a reason. Freshness
is checked against the attempt's start; old, malformed and implausibly future
status is not a recovery instruction. Model failures and historical missing
forecasts do not enter this path, nor do legacy paper or skip-prediction modes.

The second invocation still uses the normal downloader, locks and stored
cooldowns. A server cooldown longer than the one-hour wait remains binding. No
host, identity, rate limit or access restriction is bypassed. Final failures keep
their exit codes. The runner records attempt start times and its one wait in the
same scheduled log. Shutdown, process termination or the existing three-hour task
limit can interrupt recovery; this is not an always-on service.

## Tests And Deployment

Seven targeted tests passed, including real Windows PowerShell runner execution
against a synthetic Python child in an isolated temporary project. These cover
recovery success, persistent failure, native stderr with exit 0, stale/invalid
recovery metadata, non-network errors and legacy/skip modes. The one-hour sleep
is intercepted and asserted as 3600 seconds in tests, not actually elapsed. A
separate downloader test confirms zero history/quote requests and unchanged
cooldown bytes while a longer server cooldown remains active. Installer tests
stub task registration and verify hidden execution and preserved task limits.

All 164 regression tests passed in 127.605 seconds. Local logs:
`logs/runner_recovery_targeted_20261101.log` and
`logs/runner_recovery_regression_20261101.log`.

The installer now leaves outer task restarts disabled to prevent multiplying
runner attempts. The live task was also migrated after tests. A first attempt to
clear retry properties via the CIM settings setter was rejected with a missing
XML `Count` error; comparison confirmed it left the task unchanged. A structured
XML edit then removed only `RestartOnFailure`. Re-registration succeeded with
restart count 0, no interval, and an exact match to the intended XML. Action,
principal, trigger and every other setting were unchanged. The original task
definition is retained in `logs/scheduled_task_before_runner_recovery_20261101.xml.log`.

No live market refresh was needed on this Sunday. Histories remain current through
October 30, with five frozen-model forecast dates and no mature shadow outcomes.
The October 29 missing forecast and three daily outcome-revision alerts remain
visible. No model, source snapshot, first-issued forecast, outcome, account or
research acceptance threshold was changed. This replaces the October 28 recovery
mechanism, not the prediction study or its evidence.
