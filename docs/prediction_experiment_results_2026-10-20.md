# Development Experiment Results: 2026-10-20

Decision: **reject all six candidates for stable-model promotion**. Keep the existing
predictor research-only. This is a negative result, not an unsuccessful program run.
There is no evidence here for a fixed future hit rate or reliable profit.

Protocol: `config/prediction_experiment_v1.json`, fixed BEFORE fitting.
Input key: `659e2e84e58d72a1777c3de992c9399456c0107d6c39a66cfc1f375ae9804757`.
Truncated OHLCV value hash: `d78d6994fc8afa5239a02825d2e26305f9abbe960ef828622b25d9f8f8c47d64`.
Versions: NumPy 2.5.0, pandas 3.0.3, scikit-learn 1.9.0, SciPy 1.18.0, LightGBM 4.7.0.
57 symbols; 315,243 common feature rows; no extra rows lost to the enriched factors.
These feature rows include training observations and are NOT independent test trials.

All 36 registered annual records were retained: 34 complete and two rejected
non-increasing calibrations (2019 and 2022). All five starting phases were evaluated
in every successful fold. No later-than-2023 history entered any experiment.

## Three Fixed Comparisons

| Round | Candidate | Complete years | Worst annual Brier skill | Worst year/phase doubled-cost return | Minimum year/phase trades |
| --- | --- | --- | --- | --- | --- |
| 1 | Core logistic, expanding | 6 | -0.26% | -11.49% | 13 |
| 1 | Core histogram boosting, expanding | 6 | -3.68% | -25.98% | 46 |
| 1 | Core LightGBM, expanding | 6 | -4.95% | -25.18% | 68 |
| 2 | Enriched LightGBM, expanding | 6 | -3.77% | -33.80% | 90 |
| 3 | Enriched LightGBM, recent raw | 6 | -10.27% | -48.12% | 147 |
| 3 | Enriched LightGBM, recent sigmoid | 4 | -1.81% | -29.39% | 58 |

The last candidate's statistics exclude its two FAILED years and therefore cannot
be read as a full six-year track record. Every candidate failed the probability
baseline, cost-stress and drawdown gates in at least one year/phase. All except
recent raw also failed minimum active-block coverage in at least one year/phase.

## Annual Signal Diagnostics

Cells show **threshold-signal hit rate / row coverage**. These overlapping daily
signal statistics are NOT funded-trade win rates or independent sample counts.
The full local report also retains annual AUC, Brier, reliability bins and all phases.

| Candidate | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 |
| --- | --- | --- | --- | --- | --- | --- |
| Core logistic | 56.88 / 6.71% | 63.96 / 1.58% | 58.46 / 10.33% | 79.47 / 1.08% | 54.22 / 23.35% | 57.33 / 1.67% |
| Core histogram | 44.55 / 18.80% | 57.62 / 11.65% | 56.02 / 17.51% | 58.01 / 11.57% | 47.58 / 33.78% | 47.76 / 13.67% |
| Core LightGBM | 46.85 / 25.59% | 60.70 / 16.02% | 54.35 / 18.92% | 54.70 / 14.80% | 50.34 / 39.32% | 52.22 / 15.74% |
| Enriched expanding | 43.84 / 20.58% | 60.75 / 12.25% | 54.64 / 18.45% | 58.79 / 14.73% | 49.36 / 38.58% | 52.52 / 15.43% |
| Enriched recent raw | 46.46 / 46.42% | 58.91 / 35.48% | 55.42 / 48.98% | 53.68 / 45.11% | 50.93 / 54.46% | 50.58 / 38.75% |
| Enriched recent sigmoid | 49.77 / 100.00% | FAILED | 55.42 / 67.11% | 54.36 / 81.93% | FAILED | 50.42 / 11.15% |

For example, the 79.47% logistic signal hit rate in 2021 covers only 1.08% of rows.
It does not establish an approximately 80% stable model. More factors and a newer
booster did not solve the weak cross-year edge. Calibration improved some probability
errors but did not manufacture ranking skill; two calibration periods even inverted
the learned ordering and were rejected rather than hidden.

## Consequences For Continued Research

- No replacement model, new threshold, paper-account mutation or real order.
- Retain the timely first-issued forecasts and wait for genuinely new outcomes.
- Do not relax the registered gates to make these results pass.
- Prioritize new information and data quality over another parameter search on these
  years: point-in-time membership/delistings, vintage fundamentals or other lawful,
  reproducibly timestamped data require their own frozen protocol and tests.
- The current surviving universe and retrospectively adjusted vendor histories remain
  important biases. Do not describe them as a full point-in-time market dataset.

Complete immutable evidence is local under
`outputs/prediction/experiments/<input_key>/`; repeated execution verified the evidence
and skipped refitting. Source code, the frozen protocol, tests and this compact result
summary are published; account records, credentials and vendor data are not.

See [method and standalone commands](registered_prediction_experiments.md).
