# Prediction Research Guide

## Purpose And Boundaries

This is an independently runnable research baseline, not a profitable trading system.
It supplements the existing rule-based backtester rather than feeding it orders.
`trading_enabled` is always false, including when the research checks pass.
Historical data can shorten experiment preparation; it cannot substitute for genuinely
unseen future observations or guarantee a predictive edge.

## Run Without Codex

1. Double-click `start.cmd` from the project folder on Windows and choose Update Forecasts.
2. Review `outputs/prediction/report.md` and `data_inventory.csv` in the same folder.
3. For offline reruns, use `.venv\Scripts\python.exe prediction_main.py`.

The launcher checks the local Python environment and installs missing project
dependencies if necessary. First-time setup and refresh require an internet connection.
The regular scheduled self-update runner now passes `--daily --with-prediction`; no Codex
process is involved. The computer must be available and Windows Task Scheduler must
be able to run under its configured account. Daily mode skips legacy cache warmup,
paper-account simulation and framework scanning. Failures remain visible in the
scheduled log. Use `-LegacyPaper` for the original maintenance workflow and
`-FullTests` for full regression tests.

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
  The original block-based evaluation skips the whole signal date when any eligible symbol lacks an
  outcome, rather than selecting only stocks whose future prices happen to be available.
  Skipped dates still limit representativeness and are not simulated live trades.
- Moves above 80% in absolute value require review. The narrow, documented MS
  2008-10-13 exception in `config/prediction_price_reviews.json` preserves a real crisis
  observation; it does not allow arbitrary jumps for that symbol.
- Refreshes are serial, spaced by at least three seconds, with two attempts at most.
  HTTP 401/403 pauses Yahoo requests for one hour, and HTTP 429 for 15 minutes.
  The cooldown is persisted across restarts and shared with indicative quote refreshes.
  Never bypass access restrictions.
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

## Staggered Execution Study

Every full research run writes a separate execution comparison using the original
model and validation-selected threshold. Its protocol is recorded in
`execution_protocol.json` and in newly issued forecast snapshots. Existing first-issued
snapshots are retained. This protocol was developed after inspecting historical results;
it has not passed a new independent test or prospective execution validation.

Both modes start with total capital 1, use adjusted-open price proxies and fractional
research units, and pay half the configured round-trip fee on each buy and sell.
Sizing reserves the buy fee in cash. The stress simulation doubles both fees.
The comparison engine recomputes the original schedule using the same accounting
as the new schedule; tiny differences from the original block-return table are expected.

- Baseline: one capital book, at most `top_k` equal slots, scheduled every `horizon` sessions.
- Staggered: `min(horizon, top_k)` initially equal cash books, one position per book,
  with successive session offsets modulo the horizon. With the defaults, five books
  rotate daily, each holding a stock for five sessions.
- Books compound their own cash without borrowing or transfers. At most `top_k`
  distinct names can be held. Concurrent duplicate symbols are excluded; a scheduled
  book considers the next probability-ranked eligible name instead.
- Entry spending for any name cannot exceed total marked equity / `top_k`.
  Existing market weights can drift with subsequent price moves. Uninvested cash earns zero.
- The common valuation window starts at the first eligible entry and ends at the
  last planned exit inside the study partition. New entries require the full holding
  horizon to fit inside that predefined retrospective window; all positions end closed.
  This is a historical study convention, not a live mark of partially completed trades.
- Selection does not inspect targets, future returns or future outcome completeness.
  Missing selected/held price data invalidates the partition's execution study rather
  than removing that stock from the results. The report includes the validation error.

`execution_equity.csv` records daily open marks, cash, market value, exposure, name
count and fees. `execution_trades.csv` includes entry/exit dates, shares, prices,
both fees and cash P&L. Cash profit factor uses actual positive/negative realized P&L,
unlike the original block table's normalized-return profit factor. Daily-open drawdown
captures more observations than the original block-exit drawdown but still misses
intraday extremes. The additional SPY benchmark is one buy-and-hold position over the
common valuation window with actual entry/exit fees, not repeatedly reset five-day blocks.

The first comparison on data through 2026-10-16 produced:

| Period | Schedule | Net return | Daily-open drawdown | Trade win rate | Trades |
| --- | --- | --- | --- | --- | --- |
| 2022-2023 | Baseline | 13.88% | -15.61% | 47.31% | 167 |
| 2022-2023 | Staggered | 18.54% | -11.65% | 50.26% | 193 |
| 2024-2025 | Baseline | 35.75% | -22.71% | 61.36% | 88 |
| 2024-2025 | Staggered | 13.78% | -22.35% | 57.25% | 138 |
| 2026 retrospective | Baseline | -20.99% | -21.98% | 32.50% | 40 |
| 2026 retrospective | Staggered | 9.89% | -9.50% | 50.79% | 63 |

The 2026 staggered return remained +7.30% with doubled costs. Returns were worse
than the baseline in 2024-2025, so this is a tradeoff rather than consistent dominance.
`execution_start_sensitivity.csv` retains both modes for every start offset from zero
through `horizon - 1`, with no winning offset selected. In the 2026 study, shifting
the first signal date by zero to four sessions changed baseline net return from
-20.99% to +20.27%, while staggered return ranged from +9.59% to +9.89%.
This measures robustness within that historical interval, not arbitrary future start dates.
The comparison changes position selection and capital timing, not the underlying
classifier's ranking ability. It does not demonstrate a newly improved predictive AUC.
Overlapping holdings make trade counts dependent; no trade-level confidence claim
is made. Both schedules remain research-only and the existing strategy is not promoted.

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
refresh data, reuse the verified model, issue forecasts and evaluate matured records;
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

The staggered execution study above now implements the proposed equal-capital books
and exposure limits. Its remaining requirement is prospective cost/drawdown validation.
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
