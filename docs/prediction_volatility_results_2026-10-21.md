# Volatility Development Study: 2026-10-21

Decision: **all six candidates rejected; no promotion or trading**. Adding public
volatility information did not establish stable predictive improvement. These are
already-inspected development years, not fresh out-of-sample or prospective evidence.

## Registration And Data

- Protocol: `config/prediction_experiment_volatility_v2.json`, frozen before fitting.
- Input key: `cdde7416a5ced942a328e5e06cf821c8549592ad2e1620f45d3a0f3c039005d5`.
- Truncated input hash: `297e9d12c1571b30fa787d8cd4a35ae0d8c9c63f95c3ce0008d43701eec7d693`.
- Registration: 2026-10-21 11:26:58 Asia/Shanghai.
- 57 surviving stock/ETF symbols; all stock/index inputs end at 2023-12-31 before
  feature construction and hashing. Nothing from 2024-2026 tunes these models.
- Common feature support: 179,737 of 315,243 core rows, starting 2011-02-09.
  The 135,506 excluded rows reflect index availability and missing/rolling windows,
  not outcome-based selection. ALL controls/candidates use the same remaining rows.
- Twelve core features versus twenty combined features. The eight new features
  use the previous stock session, with no forward-filling missing index observations.
- Source: [official Cboe histories](https://www.cboe.com/tradable-products/vix/vix-historical-data),
  downloaded on 2026-10-20 and retained locally as immutable raw objects.
- NumPy 2.5.0, pandas 3.0.3, scikit-learn 1.9.0, SciPy 1.18.0. LightGBM 4.7.0
  is recorded in the environment but is not used by any v2 candidate.

Raw source SHA-256 values:

| Source | SHA-256 |
| --- | --- |
| VIX | `dd316faa6120a323845988c180d9d2297af29c7d4495c84d6e3e76af3f19d199` |
| VVIX | `cfcc7ec8775bfa02d45bc23e4e4cc713ec3b5e2255defe63c610980fc330df34` |
| VIX9D | `0961b5cdf0c802bffa3714f94d18f2bcdd59e933db9b9233f33cb2d98c9b9821` |

## All Candidate Decisions

Unchanged gates require positive Brier skill in EVERY year, at least 50 trades and
26 active blocks in EVERY year/starting phase, positive doubled-cost returns, and
block-close drawdown no worse than -20%. Threshold 0.55, top five, five-session
next-open holding period, 20 bps round-trip costs and seed 42 remain fixed.

| Candidate | Complete / failed folds | Worst Brier skill | Worst 40-bps year/phase return | Worst drawdown | Minimum active blocks | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| matched_core_logistic | 6 / 0 | -0.86% | -46.06% | -44.03% | 24 | Rejected |
| volatility_logistic | 6 / 0 | -2.90% | -34.54% | -39.58% | 25 | Rejected |
| matched_core_hist | 6 / 0 | -5.47% | -39.65% | -37.92% | 18 | Rejected |
| volatility_hist | 6 / 0 | -5.51% | -30.07% | -27.07% | 11 | Rejected |
| volatility_hist_recent_raw | 6 / 0 | -7.24% | -33.53% | -32.57% | 22 | Rejected |
| volatility_hist_recent_sigmoid | 4 / 2 | -2.56% | -33.84% | -38.44% | 0 | Rejected |

Each candidate fails probability, coverage, cost-stress and drawdown gates. The
sigmoid candidate additionally fails calibration in 2018 and 2019 because its fitted
slope is non-positive. Those failures remain in the record; no inverse calibration
or replacement fit was used. Its 2023 signal coverage is zero, which is a failure
of coverage, not successful abstention. Summary extrema for it cover only its four
completed folds and must not be compared as if all six years succeeded.

## Annual Diagnostics

Each cell below is **Brier skill / threshold-signal hit rate / signal coverage**, all
in percent. Brier skill compares against the fitting window's constant target-frequency
probability. Hit rates use the net-positive target after the fixed base cost; they
are not cash-constrained portfolio win rates or independent-trial accuracy estimates.

| Year | Core logistic | Volatility logistic | Core histogram | Volatility histogram | Recent raw | Recent sigmoid |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 | -0.37 / 50.68 / 32.52 | -0.90 / 47.08 / 33.14 | -5.17 / 47.64 / 42.34 | -2.22 / 49.84 / 51.51 | -7.22 / 47.50 / 49.80 | Failed calibration |
| 2019 | -0.15 / 60.70 / 12.76 | -1.59 / 51.94 / 24.13 | -1.67 / 60.52 / 26.82 | -2.96 / 55.41 / 31.09 | -1.88 / 59.31 / 36.44 | Failed calibration |
| 2020 | -0.32 / 58.77 / 36.88 | -0.08 / 55.40 / 63.75 | -5.47 / 53.66 / 44.29 | -5.51 / 56.35 / 25.45 | -3.17 / 53.59 / 56.34 | -0.02 / 54.54 / 100.00 |
| 2021 | 0.15 / 65.41 / 10.76 | 0.67 / 57.74 / 50.98 | 0.45 / 61.62 / 28.43 | -1.82 / 57.60 / 18.30 | -7.24 / 50.74 / 39.42 | -2.56 / 50.84 / 53.54 |
| 2022 | -0.86 / 49.19 / 63.05 | -2.90 / 46.23 / 66.51 | -3.03 / 48.85 / 65.51 | -2.72 / 51.47 / 65.75 | -6.75 / 50.57 / 84.98 | -0.97 / 50.10 / 87.54 |
| 2023 | -0.06 / 55.21 / 10.29 | -0.23 / 55.67 / 28.24 | -0.33 / 54.73 / 22.06 | -0.86 / 58.29 / 25.12 | -5.55 / 50.04 / 59.67 | -0.52 / N/A / 0.00 |

Volatility improves paired Brier skill in only two of six years for each expanding
model family. Histogram signal hit rates improve in four years, but coverage also
changes; this does not establish stable improvement. Worst cost-stress returns are
less negative in those paired volatility models, yet still strongly negative.
No threshold, feature, seed or date was retuned after seeing these results.

## Retained Evidence And Verification

`outputs/prediction/experiments/<input_key>/` retains all 36 fold records, including
two failures, full reliability diagnostics and all 170 successful year/phase records.
The immutable completion manifest covers the registration, folds and reports.

- `report.json` SHA-256: `6977e64e919d0d855be2e32dd4624650b94bf0358f5fff3ed6ba0455e4d37f42`.
- `completion.json` SHA-256: `ffa4b41c14a52d0ed1a01069147a41383cbd3c2bed096248b36ae9bf458dd2cf`.
- Identical-input rerun verified these files and returned without fitting.
- All 108 regression tests passed; source compilation passed.
- Tests cover lagging, missing sessions, named date indexes, cache corruption,
  retained raw versions, shared cooldown, paired row support and exclusion of future
  inputs from experiment identity. Existing daily/paper/first-issued safeguards pass.

Current vendor histories are not point-in-time vintages, the universe has survivorship
bias, outcomes overlap, and block-close drawdown misses intrahorizon losses. The
development period was previously inspected. Preserve this rejection and seek new
information or genuinely new forward observations; repeating this input or lowering
its gates would not create stronger evidence. The daily model remains unchanged.
