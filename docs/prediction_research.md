# Prediction Research Guide

## Purpose And Boundaries

This is an independently runnable research baseline, not a profitable trading system.
It supplements the existing rule-based backtester rather than feeding it orders.
`trading_enabled` is always false, including when the research checks pass.
Historical data can shorten experiment preparation; it cannot substitute for genuinely
unseen future observations or guarantee a predictive edge.

## Run Without Codex

1. Double-click `run_prediction.cmd` from the project folder on Windows.
2. Review `outputs/prediction/report.md` and `data_inventory.csv` in the same folder.
3. For offline reruns, use `.venv\Scripts\python.exe prediction_main.py`.

The launcher checks the local Python environment and installs missing project
dependencies if necessary. First-time setup and refresh require an internet connection.
The regular scheduled self-update runner now passes `--with-prediction`; no Codex
process is involved. The computer must be available and Windows Task Scheduler must
be able to run under its configured account. Earlier maintenance failures stop the
workflow and remain visible in the existing scheduled log.

For a focused integration check without running the paper engine:

```powershell
.\.venv\Scripts\python.exe self_update_main.py --skip-tests --skip-cache --skip-daemon --with-prediction
```

Run tests with `python -m unittest discover -s tests -v`.

## Data Policy

- Source: Yahoo Chart, requested from 2000-01-01. Newer listings naturally have shorter histories.
- Separate cache: `data_cache/prediction`. Legacy raw-price caches are never imported.
- All OHLC prices are scaled by adjusted-close / raw-close; volume remains reported volume.
- Only sessions completed at least 30 minutes earlier are accepted.
  Legacy data-health reports use the same completed-session calendar, so weekends
  and holidays alone do not incorrectly mark the latest available bar as lagging.
- Cache metadata records source, adjustment basis, retrieval time and SHA-256.
- Numeric, finite, unique, ordered dates, positive prices and valid OHLC ranges are checked.
- Missing observations are not forward-filled. Features need a complete rolling window;
  unobservable entry/exit labels remain missing rather than moving to another session.
  Portfolio evaluation skips the whole signal date when any eligible symbol lacks an
  outcome, rather than selecting only stocks whose future prices happen to be available.
  Skipped dates still limit representativeness and are not simulated live trades.
- Moves above 80% in absolute value require review. The narrow, documented MS
  2008-10-13 exception in `config/prediction_price_reviews.json` preserves a real crisis
  observation; it does not allow arbitrary jumps for that symbol.
- Refreshes are serial, spaced by at least three seconds, with two attempts at most.
  HTTP 401/403/429 stops remaining requests in that invocation. Never bypass access restrictions.
- Missing/stale histories or incomplete latest features prevent a clean research status.
- Data and trained artifacts remain local and are excluded from Git. Check provider
  terms before redistribution or any commercial use; free availability is not a license.

The currently configured large-cap universe contains survivors, overlapping ETF and
stock exposures, and multiple share classes. It is not a historical point-in-time
universe. Delisted stocks and membership changes remain missing. Dataset checksums
identify each run, but the provider may revise old data; keeping the original cache
and Python environment is necessary to reproduce that exact run.

## Experiment Design

Default cutoffs are fixed before model comparison:

| Partition | Dates | Purpose |
| --- | --- | --- |
| Train | 2000-2021 | Fit scaler and models |
| Validation | 2022-2023 | Choose model and threshold |
| Test | 2024-2025 | Held-out historical evaluation |
| Forward | 2026 onward | Additional retrospective monitoring, not live evidence |

All symbols share date boundaries. Labels extending across a boundary are purged.
The target is positive net return after 20 bps round-trip cost, from the next
session's adjusted open to the adjusted open five sessions later. These are
total-return price proxies, not exact executable fills or dividend cash accounting.
Features use only present/past OHLCV and SPY returns: momentum, volatility,
moving-average ratios, relative volume and relative performance. No future label
is converted into a negative class merely because it is not yet observable.

Two fixed candidates are compared: standardized logistic regression and histogram
gradient boosting. The latter disables random early-stopping splits. Validation
Brier score selects the model; validation portfolio results select among four
predefined probability thresholds, subject to minimum observations. Neither the
test labels nor the 2026 labels enter selection. Model probabilities are not
guaranteed calibrated, and the reported reliability buckets should be inspected.

Portfolio comparisons use non-overlapping five-session blocks, at most five equal
position slots, unselected slots in cash, 20 bps base costs and 40 bps stress costs.
Both an equal-weight available universe and SPY are compared over matching blocks.
The SPY reference pays the same repeated round-trip costs; it is not a frictionless
buy-and-hold benchmark. The 95% bootstrap interval resamples complete blocks, not
individual correlated stocks. It is exploratory and does not remove serial
dependence or model-selection uncertainty. Drawdowns are measured at block exits,
so intrablock losses can be worse than reported.

Checks include probability quality, observation counts, conservative excess-return
uncertainty, stress costs, drawdown and annual benchmark comparisons. Failed checks
produce `RESEARCH_ONLY`, not a silent switch to more permissive parameters. Once test
results have been inspected, repeatedly modifying models against them would turn
that interval into development data. Future upgrades need a documented new protocol.

## Actual Forward Records

`outputs/prediction/issued/YYYY-MM-DD.json` keeps the first complete forecast issued
for each signal date, with issue time, probabilities, settings and model fingerprint.
Rerunning the same day never replaces it. Keep these small files to preserve the audit
trail. The main model and large reports are replaced, not appended to SQLite.

Later runs write `issued_outcomes.csv` when real entry and exit observations exist.
Predictions issued after their assumed entry open are excluded from prospective
metrics. Only matching horizon/cost definitions are compared. Individual outcomes
overlap in time, so their Brier score is descriptive, not independent-trade evidence.
Currently the system has no mature genuinely prospective sample. The historical
`forward` table must not be presented as such a sample.

The historical training window stays fixed for this first baseline. Daily runs
refresh data, reproduce training, issue forecasts and evaluate matured records;
they do not automatically search parameters or refit on recent holdout labels.
Only locally generated joblib artifacts are written. Never load untrusted model files.

## Hit Rate Self-Check

Run `run_prediction_audit.cmd` or `python prediction_audit_main.py` after the main
prediction run. This offline diagnostic verifies the model/report metadata and
cache fingerprints before using them. It writes to `outputs/prediction/audit/`
only; the production model, threshold, status and first-issued forecasts are unchanged.

The main report now includes trade win rate, winning/losing trade counts, average
positive/negative net trade return and profit factor (sum of net wins divided by
absolute sum of net losses, using equal position-slot sizing). Undefined ratios,
including win rate when there are no trades, are reported as null/N/A, not success.
Flat trades count in the win-rate denominator but are not wins.

The audit separately reports all-signal precision and actual top-K, non-overlapping
portfolio trade wins. These are different samples. It also reports all five possible
starting offsets for the default holding period, without selecting a favorable one.
Yearly comparisons purge labels at each year boundary for both frozen and refit
models. Their counts need not sum to the combined multi-year simulation, which can
carry a position across New Year.

Annual logistic refits use expanding, trailing-five-year and trailing-ten-year
windows. Training labels must end before each evaluation year. Only the original
validation years are used for candidate comparisons; test/2026 predictions are
diagnosed for the frozen model, not used to select refit candidates. These are
post-hoc exploratory results on already inspected data, not new independent tests.

The initial audit found 2026 trade win rate 32.50% (13/40 trades, 19 active blocks),
average win +3.70%, average loss -5.98%, and profit factor 0.30. Merely shifting the
starting phase produced win rates from 32.50% to 64.10%, each on only 38-51 trades.
All-signal precision was 58.04%, but those overlapping signals were not all traded.
Neither that number nor the best phase should be advertised as achieved trading
accuracy. Trailing-window refits did not consistently improve yearly hit rate and
profitability together. No policy was promoted.

The next experiment should predeclare equal-capital staggered sleeves and exposure
limits to reduce starting-date dependence, then verify costs and drawdown prospectively.
Probability calibration, if added, needs a separate chronological calibration
segment. Raising a decision threshold alone does not improve model ranking;
always report participation and sample counts alongside precision.

See the official documentation on
[threshold tuning and overfitting](https://scikit-learn.org/stable/auto_examples/model_selection/plot_cost_sensitive_learning.html)
and [separating fitting from calibration](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.CalibratedClassifierCV).

## Reports And Failure Handling

- `status.json`: RUNNING, ERROR, RESEARCH_ONLY or RESEARCH_PASS; always trading disabled.
- `report.json` / `report.md`: settings, split sizes, metrics, reasons and limitations.
- `model_comparison.csv` / `threshold_validation.csv`: validation-only selections.
- `holdout_predictions.csv`: test predictions and outcomes for audit.
- `latest_predictions.csv`: current research probabilities, not buy recommendations.
- `portfolio_blocks.csv` / `probability_reliability.csv`: detailed diagnostics.
- `issued/` / `issued_outcomes.csv`: first-issued forecasts and subsequent evaluation.

An OS-level lock prevents overlapping prediction runs. Errors replace the status
with ERROR; previous completed report files may remain and must not be treated as
current. Dashboard status checks freshness and interrupted RUNNING reports.

## Initial Observed Result

On 2026-10-19, 57 configured symbols had verified data through 2026-10-16,
producing 355,200 feature rows. The selected logistic baseline failed the research
gates. Its 2026 retrospective portfolio return was approximately -21.03% after
assumed costs, versus +5.24% for the matching SPY blocks. The 2024-2025 result was
positive but did not establish a stable edge. No trading was enabled.

Priority next research inputs are a licensed historical universe including delistings,
point-in-time financial releases, and genuine forward records. More data alone is
not evidence that a model will improve. Paid data or cloud compute should only be
added after identifying a measurable bottleneck and approving the cost.

## References

- [Qlib research framework](https://github.com/microsoft/qlib)
- [scikit-learn time-series evaluation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
- [Histogram gradient boosting configuration](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [FRED real-time periods and vintages](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)

Latest SEC facts and revised FRED values are deliberately excluded from historical
features until publication dates and vintage handling can be verified.
