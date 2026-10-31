# Runtime Health Review: 2026-10-31

Times below are Asia/Shanghai. This is operational validation and a descriptive
data audit, not a new model experiment or evidence of improved accuracy.

## Recovery And Remaining Failures

- On October 30 at 10:37, Yahoo HTTP 403 stopped history requests. The persisted
  cooldown expired at 11:37:14 that day. All 57 histories remained through October
  28; the report's `as_of=2026-10-29` was its target session, not its data date.
- On October 31, no intervening run log existed. The live task still had
  `RestartCount=1`, `RestartInterval=PT1H` and `StartWhenAvailable=true`, but its
  last run was October 30 with exit code 1. Windows Task Scheduler's operational
  event log was disabled. System sleep/wake events exist, but do not establish
  why recovery was not executed. Configuration is not proof of execution.
- One explicit recovery was started October 31 at 16:40:49, after confirming
  the cooldown had expired and no updater was running. No cooldown, request
  spacing, endpoint or access restriction was bypassed. No task settings changed.
- All 57 histories reached October 30. Daily and frozen-shadow forecasts for
  October 30 were issued before the next entry opening. The shadow has five
  issued dates and no mature outcomes; its original model identity remains fixed.
- Recovery ended at 16:45:49 with exit code 1, not a clean success: the shadow
  audit correctly reported the missing October 29 forecast. That date was not
  backfilled, deleted from monitoring or converted into a successful observation.
- All 19 protected pre-existing files were byte-identical across recovery:
  account, frozen registration/model/manifest, daily/shadow first-issued forecasts
  and the three existing first-observed outcome archives.

The [Microsoft task settings reference](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-settingstype-complextype)
describes restart and catch-up settings. It does not establish this machine's
missing execution history. Today's recovery was explicitly triggered, not an
observed automatic retry. The scheduled log is
`logs/scheduled_self_update_20261031_164122.log`.

## First-Observed Outcome Revisions

The three previously mature daily cohorts (October 16, 19 and 20) each have
changed gross returns for COST, MS and TXN, nine rows in total. Only gross return
changed: symbols, entry/exit dates and binary target labels were unchanged. The
maximum absolute return difference was approximately 7.7941e-8 (0.00077941 basis
points). These are very small numeric differences; their cause is not established
by this comparison alone. No tolerance or correction policy was added after seeing
the differences, and `DATA_REVIEW_REQUIRED` remains set for all three dates.

Original first-observed scores remain in use with the review flags. Different
model versions remain separate. No mature frozen-shadow cohort exists yet.

| Signal date | Original file SHA-256 | Revision file SHA-256 |
| --- | --- | --- |
| 2026-10-16 | 87623829449f68fbdfcb2304ef172708bdea27948953189bab71a47e1792b315 | f5f8f14ebda3eb4f8314ec2bc3ac75b6680c7f1fd6042fc268590d7fa85714ba |
| 2026-10-19 | 2207a59609b5cc565d161e08251a50f4a2ea1ad1b07b4f68a1b0710759a5670e | c57d6583d6d4eec6692cf775324029558b120c06489fc9035eefe18303fd9b20 |
| 2026-10-20 | f876375d67645fc20e6617b50eb7d15ad638c5944d2dd6ef7fd53817c67a8c3f | 893ae3a883e19ba0621d621714889b61b3b58bf47ca9041150b9cf2e41433686 |

Raw archives, revised observations and forecast inputs remain local and ignored
by Git. The hashes identify the files audited here; this document does not modify
or acknowledge away the discrepancies.

## Health Check Repair And Regression

The previous runtime check could label a report's target session as the data date,
and accept a retained successful report even if a later run failed or remained
running. The check now labels the report session explicitly and also checks the
latest status: matching completed session, update timestamp, model hash, input
fingerprint and terminal state, with boolean true readiness in both files.
Missing, malformed, stale, mismatched, running or failed state cannot report
healthy daily data. Both available trading flags are checked. Recovery is still
permitted after freshness warnings; frozen study errors remain errors.

Six targeted tests and all 159 regression tests passed (126.629 seconds). Tests
exercise read-only/no-network behavior, interrupted/failed runs, stale target
dates, missing/malformed state, identity mismatch, strict boolean readiness and
both trading safety flags. Logs are `logs/runtime_health_targeted_20261031.log`
and `logs/runtime_health_regression_20261031.log`.

The standalone `start.cmd check` reports current daily data and verified model,
but returns 1 for the genuine October 29 shadow gap. This expected operational
failure must not be confused with a regression test failure or a clean health pass.
No frozen source, protocol, model, threshold or acceptance gate was changed.
