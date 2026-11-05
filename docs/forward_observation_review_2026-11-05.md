# Forward Observation And Network Review: 2026-11-05

## Scope

This records new observations, not a candidate search, validation pass or trading
recommendation. The frozen protocol, weights, threshold, costs, universe and
implementation remain unchanged. No inspected 2024-2026 history was re-searched.
The historical experiment registry still identifies input
`b68b430a6f2153a875963e892e81705081ac65a6664ef7757da73b8b236862a6`.

## Recovery And First Mature Cohorts

On November 4 at 18:40 China time, the normal daily refresh completed after the
previous DNS resolution failure. All 57 histories were verified through November 3.
The downloader's existing serial pacing and cooldown policy were used; no access
restriction was bypassed. Daily and frozen forecasts for November 3 were issued
before the November 4 entry open. Missing October 29 and November 2 forecasts were
not backfilled. The post-update health check therefore returned exit code 1 despite
fresh data and successful publication. This is not a clean health pass.

The frozen study first observed complete outcomes for the October 23 and October
26 cohorts. Both were preserved in its first-observed outcome archive. Together:

| Measure | Observation |
| --- | --- |
| Complete eligible dates / rows | 2 / 114 |
| Classification accuracy at probability 0.5 | 52.63% (60/114) |
| Always-positive classification baseline | 51.75% (59/114) |
| Brier score / constant-probability baseline | 0.248307 / 0.25 |
| Nonoverlapping cohort windows | 1 |
| Qualified ranked signals / signal windows | 0 / 0 |
| Ranked-signal hit rate | N/A, not 0% or 100% |
| Frozen outcome revision review dates | 0 |
| Evidence status | INSUFFICIENT_PROSPECTIVE_DATA |

These are net-positive classification outcomes under the existing five-session,
20-basis-point policy, not daily direction accuracy or realized portfolio profits.
The 114 rows share dates and overlapping holding periods, not 114 independent
trials. A one-row advantage over the baseline is not evidence of a stable edge.
No qualifying signal in these mature cohorts justifies lowering the threshold.
The fixed requirements remain 126 complete dates, 50 ranked signals and 26
nonoverlapping signal windows, with no unresolved outcome review. Even reaching
them would permit review only, not automatic deployment.

There are six frozen forecast dates in total; four still await complete outcomes.
Daily models are a different stream: five eligible dates under five policies,
three retained outcome-revision alerts, and no mature evidence for the current
daily model. They are not pooled with the frozen study or presented as one model's
accuracy. The ordinary daily cache-key change caused the existing historical
training workflow to run; this did not replace the frozen model or select a new
candidate from recent outcomes. Trading remains disabled.

## November 5 Interruption

The standalone Windows task ran at 17:05 China time and reached its one permitted
recovery attempt at 18:05, without Codex driving it. Both attempts ended STALE_DATA;
the final recorded cooldown was Yahoo HTTP 403 through 19:05:26 China time
(`2026-11-05T11:05:26.946212+00:00`). The runner retained exit code 1. This confirms
the bounded recovery path executed, not that provider access or scheduling
availability is guaranteed. November 4 bars were not obtained, and no November 4
forecast was issued as of this review. Its publication deadline had not yet passed.

No additional provider request was made during this active cooldown. Existing
results were reviewed offline. The 403's underlying cause is not established;
the November 3 DNS error must not be used to explain a different day's HTTP error.

The engineering change adds a read-only `network cooldown` row to runtime checks:
active reason and UTC deadline are visible; malformed/unreadable metadata warns;
missing/expired metadata explicitly does not establish connectivity. Checks neither
download nor delete or rewrite cooldown state. Warnings still permit the normal
workflow, whose downloader remains responsible for enforcing the cooldown.

## Reproducibility

The November 4 refresh retained byte-identical hashes for all 28 distinct protected
files captured before that run, including existing forecasts/outcomes/revision
records, frozen model/registration and the paper account. The following are file
SHA-256 values, except where an identifier is explicitly labeled as a payload key.
Local price data, feature inputs, model artifacts and logs are not published.

| Artifact | SHA-256 |
| --- | --- |
| Frozen protocol file | `d2b165e32803ee0edcd8d5005d8148350e38c88183530161ea68b179d65762c6` |
| Frozen registration file | `a99b63af698509271d2f9babc20e183f66b8f954fecbaeaeceff004570aaf957` |
| Frozen model | `643a0f16335ec75742425a9b5646fd5e350aa903725550415853ecad0595272c` |
| October 23 first-observed outcome file | `98966c0cbeef298b2e0e7470002d61e87082893159b73eb3d77d1bee9f80a3b5` |
| October 26 first-observed outcome file | `ccf6334bcb07c20cd4b517f6d0f672bc04162e97e07940e71094527cf38957af` |
| November 3 frozen forecast | `ca91fd06bee0e6b770e0bae84b8978b25a9980693585ab1343f39ee79ab3e41a` |
| November 4 data inventory snapshot | `0a66a477dcb93cd55e2cce03a657cf5fa2ddc0da95d8fd83ec05542d71b8eebc` |
| November 4 frozen scorecard report | `520bc2c5d51fd3946dad4cdff7c68b698b203f54300c19de566d4dd90434dbee` |
| November 4 refresh log | `790782b44bbf635c6fd99d322543a9ce9bcc648fbee3ffe56e87893b33818a17` |

The November 4 input fingerprint was
`f62aa0f9ad6df4a96cfc871b15a20bc0f991600238aa86eed319e282ba832ac8`;
the daily model was
`76f058a8b8474033aea7cbf7a3d20d47c703e782caba6dfee89d346fcd225f4d`.
Each frozen first-issued forecast retains its exact feature inputs and source-file
hashes. Rolling inventory/report paths may change on later runs; immutable forecast
and outcome archives are the evidence source, not today's rolling status file.

## Verification

November 4's unchanged-code regression passed all 164 tests. November 5's targeted
runtime tests passed all 10 cases, including active/expired/missing cooldowns,
invalid timestamps and schemas, unreadable metadata, no network and no mutation.
The live read-only check correctly reported the active 403 cooldown, stale bars
and shadow STALE_DATA; its exit code 1 remains an operational failure, not a test
failure. The full regression then passed all 168 tests in 150.612 seconds.
Local logs are `logs/network_health_targeted_20261105.log`,
`logs/network_health_regression_20261105.log` and
`logs/network_health_live_20261105.log`. This change does not resolve the provider
restriction, remove historical gaps or satisfy the model's evidence requirements.
