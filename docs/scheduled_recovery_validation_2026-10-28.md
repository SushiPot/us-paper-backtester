# Scheduled Recovery Validation: 2026-10-28

All times below are Asia/Shanghai. This is an operational repair, not a model
experiment or evidence of improved prediction accuracy.

## Observed Failure And Recovery

- The 18:05 run received Yahoo HTTP 403 on the first history request and persisted
  a cooldown until 19:05:40. All 57 histories remained stale; no new forecast was
  published from those stale inputs. The task correctly returned exit code 1.
- A single explicit recovery was started after that deadline. The existing
  downloader retained its request spacing, cooldown checks and validation rules.
  No endpoint, identity, access restriction or cached cooldown was bypassed.
- Recovery completed at 19:10:34 with exit code 0. All 57 histories were current
  through 2026-10-27, and the frozen shadow study retained three issued dates,
  no missing publication dates and no mature shadow outcomes.
- The account, existing first-issued forecasts, frozen model/registration and
  existing first-observed outcomes were checked across recovery: all 13 protected
  files were byte-identical. New daily model evidence remains separate.
- Logs remain local: `scheduled_self_update_20261028_180532.log` and
  `scheduled_self_update_20261028_190632.log` under `logs/`.

## Regression And Deployment

The installer now configures one restart after one hour only for daily prediction
mode. Legacy paper mode still has zero restarts. A real ScheduledTasks settings
object is tested while registration is replaced by a verified function stub; the
tests never create a Windows task. A separate test proves a remaining server
cooldown prevents both history and quote requests across loader restarts.

The first added cooldown test incorrectly expected the cooldown message to take
precedence over a missing-cache diagnostic. That assertion failed, including in
the first full regression run. It was corrected to check the persisted blocked
state and missing-data status; zero network calls and unchanged cooldown bytes
remain required. The final targeted tests and all 153 regression tests passed.

The live task's retry count/interval were updated to 1/PT1H. Its other settings,
action, trigger and principal were compared before and after and were unchanged.
The previous task definition is retained locally in
`logs/scheduled_task_before_retry_20261028.xml.log`. Today's recovery was explicitly
triggered after cooldown; the future one-hour automatic restart delay was verified
as configuration, not tested by deliberately causing another live provider failure.
