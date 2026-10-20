# Registered Prediction Experiments

This runner is isolated from the daily predictor, accounts and first-issued forecasts.
It reads the verified local adjusted-price cache and never contacts a data provider,
submits orders, changes a threshold or replaces the active model.

The [2026-10-20 results](prediction_experiment_results_2026-10-20.md) rejected all six
candidates. Failed experiments are evidence to retain, not parameters to conceal.

## Run Without Codex

From the project directory on Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-prediction-research.txt
.\.venv\Scripts\python.exe prediction_experiment_main.py
```

LightGBM is optional and pinned for research reproducibility. Daily predictions and
results viewing still require only `requirements.txt`. Missing research dependencies
produce retained failed candidate records rather than silent algorithm substitution.
The separate, authorized Codex research heartbeat runs at 08:00 Asia/Shanghai;
it requires the computer and Codex desktop app to be available. The existing daily
stock-program task and the standalone commands above do not require Codex.

## Frozen Protocol

`config/prediction_experiment_v1.json` was written before fitting these candidates.
Six annual development folds cover 2018-2023. All input histories are truncated at
2023-12-31 BEFORE building any features or labels. Training labels must mature
strictly before the evaluation year; evaluation labels cannot cross year-end.
Already-inspected 2024-2026 outcomes are not selection inputs or fresh holdouts.

Three fixed comparisons, not adaptive searches:

1. Existing 12 factors: standardized logistic regression, histogram gradient boosting,
   and CPU LightGBM, with expanding training histories.
2. LightGBM with the same rows and 59 causal factors: the 12 existing factors plus
   OHLC bar geometry and five fixed rolling windows of normalized price/volume measures.
3. Five-year LightGBM with its last 126 eligible training dates reserved for calibration.
   The raw and sigmoid candidates use the SAME purged fit rows and base estimator.
   Only the sigmoid candidate uses those reserved targets. A non-increasing calibration
   curve fails explicitly; it is not silently inverted or replaced with the raw model.

Seed 42, threshold 0.55, five positions, five-session next-open holding period,
20 bps round-trip cost, and doubled-cost stress are fixed. There is no threshold,
seed or favorable start-date search. Every starting phase is retained separately.

For a development pass, EVERY annual fold must beat its training-prior Brier baseline.
EVERY year/phase needs at least 50 trades and 26 active blocks, positive doubled-cost
return, and drawdown no worse than -20%. A pass is only a shadow-review eligibility
flag, not evidence of stable real-time accuracy, permission to trade, or promotion.

## Evidence And Resumption

The runner saves an immutable registration before fitting. It records the exact
protocol, verified source-file hashes, truncated input-value fingerprint, symbols,
library versions and implementation hashes. The run directory is content-addressed:
`outputs/prediction/experiments/<input_key>/`.

- `registration.json`: protocol and input provenance.
- `<candidate>-<year>.json`: successful or failed fold, checksummed for resumption.
- `report.json` / `report.md`: all candidates, failures and annual diagnostics.
- `starting_phases.csv`: all phases, including bad phases.
- `summary.csv`: fixed cross-year gates and rejection reasons.
- `completion.json`: hashes of completed evidence files; corruption stops reuse.
- `../latest.json`: pointer to the most recently completed experiment.

An interrupted run resumes saved folds. A completed run with identical inputs is
verified and reused without fitting again. Changed inputs/code/versions receive a
different directory; old failures remain. A separate OS lock prevents two researchers
from writing the same experiment concurrently without locking the daily predictor.

## Honest Limits

The current stock list consists of surviving names, not historical point-in-time index
membership. Delisted companies are absent. Vendor-adjusted bars are not vintage
snapshots. Daily labels overlap and stocks on the same date are correlated: row/trade
counts are not independent trials. Block-close drawdown misses intrahorizon losses.
These limitations preclude treating a favorable development score as a deployment
guarantee. New, timely archived forward predictions remain the confirmation path.

The additional factors are an independently implemented OHLCV subset inspired by
[Qlib Alpha158 definitions](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/loader.py),
NOT a full Alpha158 reproduction (no VWAP is fabricated). CPU determinism follows
[LightGBM's parameter guidance](https://lightgbm.readthedocs.io/en/stable/Parameters.html#deterministic);
different library builds and systems can still differ, which is why versions are recorded.
