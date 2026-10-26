# Frozen Baseline Registration: 2026-10-26

## Purpose

Five existing daily forecast dates have five distinct model hashes. Those versions
must not be pooled to claim a stable model. This study retains the currently verified
model and observes it on future inputs even when ordinary daily training changes.
It is an engineering improvement to evidence continuity, not an accuracy gain.
No historical experiment was rerun and no alternative anchor was searched.

## Immutable Identity

- Protocol: `config/prediction_shadow_v1.json`, `frozen-baseline-forward-v1`.
- Registration time: 2026-10-26 14:17:28 Asia/Shanghai, before the next entry open.
- Registration payload SHA-256: `0773686ce1379f9ea5d8465f8f4011e0c8a503735d0e71b42d00383377ef55a8`.
- Model SHA-256: `643a0f16335ec75742425a9b5646fd5e350aa903725550415853ecad0595272c`.
- Training input key: `6ad683b7fb18ec9b7ea1f10e3f95f836fcc457306b498a7090e3a3fb81f73d2c`.
- Manifest SHA-256: `c002fc08d9a35a941133b353497fa8e2c57712f58814f01677baa2ca2e64e3b8`.
- First shadow forecast: signal session 2026-10-23, actually issued 2026-10-26
  14:17:46 Asia/Shanghai for the next modeled entry at 21:30 the same day.
  The issue timestamp is not backdated to the signal session.
- First feature-input SHA-256: `82ebe899762c7424b558063d3e91e23aebb1664e8836c35a7b92730ccf3b2ebd`.
- First issued snapshot file SHA-256: `a562846e854030ccea268b56bcffda2badcfa3e39137b0f6597b2cdf7054d80a`.

The registration retains the complete protocol, policy, source hashes, model metadata
and environment versions. The first-issued forecast retains exact features for all
57 symbols and source-file hashes. They are local under
`outputs/prediction/shadow/frozen-baseline-v1/`; raw artifacts are not published.

## Verification And Initial Observation

- Nine focused shadow tests and the complete 139-test regression suite passed.
- Compilation and whitespace checks passed.
- The offline daily run reused the existing model, made no new fit, and reported
  `OBSERVING` for the shadow stream with a valid publication window.
- Hashes of the account, active model, active manifest and five original issued
  forecasts were unchanged across registration and offline execution.
- The existing Windows scheduled task was triggered independently and completed
  with exit code 0 at 2026-10-26 14:19:15 Asia/Shanghai. It reused the model and ran
  the shadow stream automatically. The same eight daily files plus the four
  frozen shadow artifacts/first forecast remained byte-identical.
  Local log: `logs/scheduled_self_update_20261026_141856.log`.
- Initial qualifying signals: zero. Mature eligible shadow dates: zero.
- Minimum observation requirements remain 126 complete dates, 50 ranked signals
  and 26 nonoverlapping signal windows, with no unresolved outcome review.
  Meeting these counts only permits review; it does not pass performance gates.
- No policy was promoted, no real trading was enabled, and no accuracy or profit
  claim can be supported by this initial observation.

The tests cover independent outcomes, preservation of losses and first-issued
features, same-day reruns, publication timing, checksum validation before loading,
partial registration conflicts, environment/policy drift, locks, and isolation of
shadow failures from ordinary daily forecasts. Daily operation still uses the
existing standalone Windows runner and requires no Codex process.
