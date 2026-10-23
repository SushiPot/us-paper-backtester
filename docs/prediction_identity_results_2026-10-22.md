# Stock Identity Development Study: 2026-10-22

Decision: **both candidates rejected; neither replaces the daily model**. Adding
stock-specific intercepts increased signal coverage but did not establish stable
probability quality or positive after-cost performance. These development years
have already been inspected and are not fresh holdout or prospective evidence.

## Registration And Data

- Protocol: `config/prediction_experiment_identity_v3.json`, frozen before fitting.
- Input key: `b68b430a6f2153a875963e892e81705081ac65a6664ef7757da73b8b236862a6`.
- Truncated input hash: `74b707a94b814cef30ae28a0405538f5c91d328e3d01bc6dd7dea45f5cac6d58`.
- Registered at 2026-10-22 14:55:56 Asia/Shanghai; report finalized on October 23
  after confirming the interrupted full regression run had passed.
- 57 surviving stock/ETF symbols; 315,243 common core feature rows, with zero
  additional exclusions for enriched or volatility features.
- All histories end at 2023-12-31 before feature creation, encoding, baseline
  estimation, model fitting and input-value hashing. No 2024-2026 outcome is used.
- NumPy 2.5.0, pandas 3.0.3, scikit-learn 1.9.0, SciPy 1.18.0. LightGBM 4.7.0 is
  recorded in the environment but is not used by either candidate.

The hypothesis is a single predeclared pair: standardized pooled logistic regression
versus the same regression with one-hot stock identities and regularized intercepts.
Both use C=0.1, max_iter=500, seed 42, twelve numeric factors, expanding training
history and no calibration. Categories are learned only from each fitting fold.
An unseen stock gets an all-zero identity vector; none occurred in the actual
evaluation folds. This does not fit separate stock-specific slopes.

Both candidates have identical row support and labels in every annual fold:

| Evaluation year | Training rows | Evaluation rows |
| --- | --- | --- |
| 2018 | 228,888 | 13,965 |
| 2019 | 243,195 | 14,022 |
| 2020 | 257,559 | 14,079 |
| 2021 | 271,980 | 14,022 |
| 2022 | 286,344 | 13,965 |
| 2023 | 300,651 | 13,908 |

Training labels mature strictly before the evaluation year; evaluation labels do
not cross year-end. All five possible rebalance starting phases are evaluated.

## Gates And Decisions

The existing gates require positive Brier skill in EVERY year, at least 50 trades
and 26 active blocks in EVERY year/phase, positive doubled-cost return, and
block-close drawdown no worse than -20%. The threshold is 0.55, top five positions,
five-session next-open holding period, 20 bps round-trip base cost and 40 bps stress.

One additional gate requires positive Brier skill against each stock's historical
net-positive frequency in EVERY year. These baseline probabilities use only that
fold's purged fitting rows, with the pooled fitting prior for unseen stocks. This
checks whether the model adds information beyond each stock's historical win rate.

| Candidate | Complete / failed folds | Worst pooled-prior skill | Worst stock-prior skill | Worst 40-bps year/phase return | Worst drawdown | Minimum trades / active blocks | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| matched_pooled_logistic | 6 / 0 | -0.26% | -0.47% | -11.49% | -36.15% | 13 / 4 | Rejected |
| stock_intercept_logistic | 6 / 0 | -0.89% | -0.43% | -37.00% | -39.91% | 133 / 39 | Rejected |

Each column is a separate worst-case statistic; the extrema need not occur in
the same year or phase. Returns are not compound multi-year performance.

Both fail the pooled-prior, stock-prior, cost-stress and drawdown gates. The pooled
control additionally fails coverage. Stock intercepts pass coverage in every
year/phase but do not pass the remaining gates. No execution failed and no candidate,
year or bad starting phase was removed.

## All Annual Diagnostics

Brier skill is `1 - model Brier error / baseline Brier error`; positive is better.
Both baselines use fitting data only. Signal hit rate is the fraction of
threshold-qualified rows with a net-positive target at the fixed base cost; coverage
is the fraction of evaluation rows qualifying. Neither is an independent-trial
accuracy estimate or the cash-constrained portfolio win rate.

| Candidate | Year | Pooled-prior skill | Stock-prior skill | AUC | Signal hit rate | Coverage |
| --- | --- | --- | --- | --- | --- | --- |
| matched_pooled_logistic | 2018 | 0.15% | 0.20% | 0.517 | 56.88% | 6.71% |
| stock_intercept_logistic | 2018 | 0.06% | 0.11% | 0.519 | 54.32% | 15.27% |
| matched_pooled_logistic | 2019 | -0.02% | -0.13% | 0.512 | 64.13% | 1.59% |
| stock_intercept_logistic | 2019 | 0.20% | 0.09% | 0.519 | 62.56% | 9.60% |
| matched_pooled_logistic | 2020 | -0.15% | -0.47% | 0.529 | 58.46% | 10.33% |
| stock_intercept_logistic | 2020 | 0.38% | 0.06% | 0.549 | 60.44% | 16.63% |
| matched_pooled_logistic | 2021 | 0.18% | 0.19% | 0.534 | 79.61% | 1.08% |
| stock_intercept_logistic | 2021 | 0.19% | 0.20% | 0.528 | 59.08% | 12.81% |
| matched_pooled_logistic | 2022 | -0.26% | 0.20% | 0.522 | 54.20% | 23.36% |
| stock_intercept_logistic | 2022 | -0.89% | -0.43% | 0.504 | 48.68% | 33.67% |
| matched_pooled_logistic | 2023 | -0.16% | -0.33% | 0.496 | 57.51% | 1.68% |
| stock_intercept_logistic | 2023 | 0.08% | -0.09% | 0.518 | 57.20% | 10.99% |

The identity model improves paired Brier error in four of six years. It beats the
pooled prior in five years, but the stock-specific prior in only four. Its weakest
cost-stress result is worse than the control's. The control's 79.61% signal hit rate
in 2021 covers only 1.08% of observations and fails the coverage requirement; it is
not evidence of stable 80% accuracy. No parameter or threshold was retuned afterward.

## Retained Evidence And Verification

`outputs/prediction/experiments/<input_key>/` retains all twelve completed fold
records, reliability diagnostics and all sixty year/phase records. The completion
manifest checksums the registration, every fold and reports. Price histories and
generated evidence remain local; this document records the result and hashes.

- Runner source SHA-256 at registration: `167256c3202e9d12611ebb13f3801fce661996bf69297a792363857361e05d69`.
- `report.json` SHA-256: `9befb7f2bfed711cf23402ad9a7ae1ca973a4832045daa913669f452e39e02b2`.
- `completion.json` SHA-256: `dd1fc225d7c7f9001b7a4d6970b7b4fd3db939a8c40e7316ac30ca2ed348bd50`.
- The identical-input rerun on October 22 verified and reused existing results
  without fitting. The October 23 continuation verified the completion manifest
  and registered protocol without refitting against subsequently refreshed caches.
- The initial local suite passed all 128 tests, including five new stock-identity
  tests. The [first remote run](https://github.com/SushiPot/us-paper-backtester/actions/runs/39963367110)
  exposed an older test's assumption that downloaded and CSV-parsed date resolutions
  must differ; both were microseconds in that environment. The integration test now
  checks equal values, with a separate explicit seconds/milliseconds/microseconds/
  nanoseconds test of model reuse and input preservation. All 129 local regression
  tests passed after that test correction; experiment code and saved results did
  not change. Source compilation and the standalone launcher self-check also passed,
  with the latter reporting the then-stale market cache as a warning.
- Tests cover train-only categories, unseen-stock handling, stronger-baseline
  rejection, zero-error baseline handling, exact paired row support, purged labels,
  offline real fitting, registration before fitting, and future-input reuse.

The universe omits delisted names and historical membership changes. Adjusted prices
are current vendor vintages; correlated stocks and overlapping labels reduce the
effective sample size. Block-close drawdown misses intrahorizon losses. These are
already-inspected development years. The experiment rejects this fixed hypothesis
under the registered gates; it does not establish that every stock-aware model will
fail. Original issued forecasts and daily policy remain separate from this study.
