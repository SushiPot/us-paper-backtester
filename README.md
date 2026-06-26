# US Paper Backtester

A Python-based US stock backtesting and local paper trading system.

The default workflow does **not** require a brokerage account. It runs a fully local paper trading simulation using historical market data from `yfinance` / Yahoo Finance, virtual cash, CSV-based positions, order logs, trade logs, and performance reports.

IBKR Paper Trading support is kept in the codebase as an optional module, but it is **not enabled by default**.

## Project Stages

- Stage 1: Offline backtesting
- Stage 2: Local paper trading with no brokerage account required
- Stage 3: Optional IBKR Paper Trading module, disabled by default

## Strategy

The current strategy trades:

- TSLA
- NVDA
- AAPL
- SPY
- QQQ
- SPCX

Buy strategy 1, strict golden cross:

- MA20 crosses above MA60
- RSI(14) is below 70
- Current volume is above the 20-day average volume

Buy strategy 2, trend follow:

- MA20 is above MA60
- Close is above MA20
- RSI(14) is between 45 and 70
- Current volume is at least 80% of 20-day average volume
- Close is no more than 8% above MA20
- 5-day return is not worse than -3%
- Uses 40% of the normal per-position risk budget

Sell conditions:

- MA20 crosses below MA60
- Stop loss: -8%
- Take profit: +20%
- Holding period exceeds 30 trading days

Risk and position rules:

- Initial virtual cash: 10,000 USD
- Maximum position size: 20% of account equity
- SPCX observation position limit: 10% of account equity
- Maximum simultaneous positions: 5
- No leverage
- No short selling
- No options
- Daily loss limit: 2%
- Maximum account drawdown: 10%

## Stocks And Options Research

The project intentionally excludes crypto trading. Options support is research-only at this stage and never creates orders.

Generate a mature framework integration plan:

```powershell
python framework_integration_main.py
```

Outputs:

- `outputs/framework_integration_plan.csv`
- `outputs/framework_integration_plan.md`

The plan tracks which open-source projects are useful as references:

- Qlib for factor research discipline and label evaluation
- NautilusTrader for deterministic event-driven architecture
- QuantConnect LEAN for stock/options architecture boundaries
- backtrader for classic broker/data/strategy separation
- backtesting.py for lightweight strategy interfaces
- vectorbt for fast research sweeps
- QuantStats for performance analytics
- PyPortfolioOpt / Riskfolio-Lib / skfolio for portfolio risk research

Scan stock/ETF option chains for research:

```powershell
python options_research_main.py
```

Outputs:

- `outputs/options_chain_snapshot.csv`
- `outputs/options_liquidity_watchlist.csv`
- `outputs/options_research_summary.csv`
- `outputs/options_research_report.md`

The option scanner records:

- Bid/ask/mid
- Spread percentage
- Open interest
- Volume
- Implied volatility
- Strike moneyness
- A liquidity watchlist flag

Safety boundary: this module is data analysis only. It does not connect to a broker, does not send option orders, and does not change local paper positions.

## Backtesting Outputs

Run the historical backtest:

```powershell
python main.py
```

The backtest writes:

- `outputs/trade_log.csv`
- `outputs/backtest_report.csv`
- `outputs/equity_curve.csv`
- `outputs/equity_curve.png`
- `outputs/performance_metrics.csv`
- `outputs/backtest_strategy_scorecard.csv`

The trade log now includes strategy attribution and entry/exit diagnostics:

- Strategy name
- Signal score
- Entry RSI
- Entry MA gap
- Entry volume ratio
- Entry distance from fast MA
- Entry 5-day return
- Exit RSI
- Exit MA gap

`outputs/backtest_strategy_scorecard.csv` compares each strategy by trade count, win rate, average return, realized PnL, average signal score, average entry RSI, and average entry volume ratio.

## Local Paper Trading

This is the recommended mode.

It does not connect to IBKR or any broker. It only uses local files and market data from `yfinance` / Yahoo Finance.

Run once:

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
python local_paper_main.py --once
```

Local paper trading features:

- Uses `virtual_cash` instead of real money
- Saves virtual positions to `outputs/positions.csv`
- Saves virtual orders to `outputs/paper_order_log.csv`
- Saves virtual fills to `outputs/paper_trade_log.csv`
- Saves account state to `outputs/virtual_account.csv`
- Saves account history to `outputs/account_history.csv`
- Generates `outputs/local_paper_report.csv`
- Generates `outputs/local_equity_curve.png`
- Generates `outputs/strategy_scorecard.csv`
- Simulates 0.05% slippage by default
- Simulates commission at 0.005 USD per share, minimum 1 USD
- Allows only one order decision per run by default
- Includes SPCX as a high-volatility observation symbol with a stricter 10% position cap
- Writes signal explanations, strategy names, and signal scores to `outputs/decision_log.csv`
- Attributes positions, orders, fills, realized PnL, unrealized PnL, win rate, and live data sufficiency by strategy
- Writes decision diagnostics such as RSI, MA gap, volume ratio, distance from MA, and 5-day return

Local paper trading outputs:

- `outputs/positions.csv`
- `outputs/virtual_account.csv`
- `outputs/account_history.csv`
- `outputs/paper_order_log.csv`
- `outputs/paper_trade_log.csv`
- `outputs/decision_log.csv`
- `outputs/run_log.csv`
- `outputs/local_paper_report.csv`
- `outputs/strategy_scorecard.csv`
- `outputs/strategy_scorecard_report.md`
- `outputs/local_equity_curve.png`

## Signal Evaluation And Relative Strength Filter

Every local paper run now evaluates historical buy signals with forward-return labels. This is designed to answer a practical question before increasing confidence in the system: did the signal actually select better-than-average future returns?

Signal evaluation outputs:

- `outputs/signal_evaluation.csv`
- `outputs/signal_evaluation_summary.csv`
- `outputs/signal_evaluation_report.md`

The report compares:

- `enabled_blend`: all enabled technical buy strategies
- `enabled_blend_relative_strength_filter`: technical buy signal plus relative-strength filter
- `trend_follow`
- `strict_golden_cross`

Current label definition:

- 5, 10, and 20 trading day forward returns
- Positive label when the future return is at least 3%

The relative-strength filter ranks the stock universe by:

- 20, 60, and 120 day momentum
- Relative return versus SPY
- Trend state
- Pullback quality
- RSI quality
- Volatility penalty

New buy orders are allowed only when the symbol passes the relative-strength gate. The default minimum score is now `70`, which makes the local simulation more selective. In a neutral market environment, the system only accepts the top 2 relative-strength names.

Relative-strength outputs:

- `outputs/relative_strength_rank.csv`
- `outputs/relative_strength_report.md`

Safety note: these filters only affect the local simulation decision layer. They do not connect to a broker and do not place real orders.

## Data Health And Market Environment

The system includes two read-only diagnostics that improve feedback without changing orders.

Refresh data health:

```powershell
python data_health_main.py
```

Outputs:

- `outputs/data_health_summary.csv`
- `outputs/data_health.csv`
- `outputs/data_health_report.md`

Refresh market environment:

```powershell
python market_environment_main.py
```

Outputs:

- `outputs/market_environment_summary.csv`
- `outputs/market_environment.csv`
- `outputs/market_environment_report.md`

The market environment layer uses SPY and QQQ to classify:

- `RISK_ON`
- `NEUTRAL`
- `RISK_OFF`

It checks MA50, MA200, 5-day return, 20-day return, and 20-day realized volatility. The result is advisory only: it appears in the dashboard and RiskAgent warnings, but it does not place orders or connect to a broker.

## Free Online Data

The project can refresh extra free public data without any broker account or paid API key:

```powershell
python online_data_main.py
```

Sources:

- FRED public CSV downloads for macro indicators such as VIX, Treasury yields, yield curve, federal funds, unemployment, CPI, and S&P 500
- SEC EDGAR Companyfacts API for public company fundamentals on AAPL, NVDA, and TSLA

Outputs:

- `outputs/macro_indicators.csv`
- `outputs/macro_environment_summary.csv`
- `outputs/macro_environment_report.md`
- `outputs/fundamental_snapshot.csv`
- `outputs/fundamental_summary.csv`
- `outputs/fundamental_report.md`

`RiskAgent` reads `macro_environment_summary.csv` and adds a warning when the macro backdrop suggests smaller simulated buy sizes or no new buys. SEC fundamentals are currently advisory data only. They help you compare company quality and valuation research later; they do not trigger trades by themselves.

For best SEC compliance, you can set a contact user agent before running:

```powershell
$env:SEC_USER_AGENT="us-paper-backtester/1.0 your-email@example.com"
python online_data_main.py
```

## Strategy Scorecard

The local paper trader now keeps strategy-level attribution. Each virtual position, order, and fill stores:

- `strategy_name`
- `signal_score`

After every local paper run, the program refreshes:

- `outputs/strategy_scorecard.csv`
- `outputs/strategy_scorecard_report.md`

Refresh it without downloading new market data:

```powershell
python strategy_scorecard_main.py
```

The scorecard compares strategies by:

- Decision count
- Buy and sell signal count
- Submitted and rejected order count
- Buy and sell fill count
- Open position count
- Open market value
- Realized PnL
- Unrealized PnL
- Win rate
- Average profit/loss ratio
- Live paper data sufficiency status

This is designed to keep the system conservative: a backtest-leading strategy is not automatically trusted until it also builds enough live paper evidence.

## Strategy Health

The research workflow also generates a conservative strategy health layer inspired by open-source quant analytics projects such as QuantStats, pyfolio, and empyrical.

It writes:

- `outputs/strategy_health.csv`
- `outputs/market_regime.csv`
- `outputs/strategy_health_report.md`

The health score combines performance, risk, signal quality, and data sufficiency. If there is not enough live paper history or too few virtual fills, the program marks the strategy as observation-only instead of pretending the model is mature.

## Dashboard

Generate a static local dashboard from the CSV outputs:

```powershell
python dashboard.py
```

The dashboard is written to:

```text
outputs/dashboard.html
```

It shows:

- Current equity
- Virtual cash
- Total return
- Max drawdown
- Sharpe ratio
- Open positions
- System Status lights for data health, market environment, daemon freshness, local account state, positions, and SQLite
- Equity curve
- Recent decisions
- Recent orders
- Recent trades

The status-light table is also saved to:

```text
outputs/dashboard_status.csv
```

Open `outputs/dashboard.html` in your browser after generation.

## Web App

Windows CMD quick start:

```cmd
run_web.cmd
```

Open the website and launch the server in one step:

```cmd
run_web_open.cmd
```

Run the local website:

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
python web_app.py
```

Then open:

```text
http://127.0.0.1:5000
```

Check whether the website is running:

```cmd
check_web.cmd
```

Stop the local website:

```cmd
stop_web.cmd
```

## One-Click Daily Commands

These Windows CMD launchers are intended for day-to-day use from the project folder or from desktop shortcuts:

```cmd
refresh_all.cmd
status_check.cmd
open_dashboard.cmd
git_push.cmd
run_daemon.cmd
```

- `refresh_all.cmd`: refreshes free online data, runs the local paper simulation once, regenerates the dashboard, and prints status
- `status_check.cmd`: prints Git status, system status lights, virtual account, positions, and daemon state
- `open_dashboard.cmd`: regenerates and opens `outputs/dashboard.html`
- `git_push.cmd`: pushes the current `main` branch to GitHub
- `run_daemon.cmd`: starts the long-running local daemon

The desktop shortcut named `US Paper Backtester PowerShell` opens PowerShell in the project folder, starts the local web server, and opens `http://127.0.0.1:5000` once the server is ready. Keep that PowerShell window open while using the website.

The web app shows the same local paper trading account state in a browser:

- Current equity and virtual cash
- Total return, max drawdown, Sharpe ratio, and open positions
- System Status lights for quick health checks
- Equity curve
- Current positions
- Recent decisions, orders, and trades
- Macro environment and SEC fundamental tables
- Strategy scorecard
- Optimization top 10 results

The web app can run:

- `local_paper_main.py --once` through the **Run Local Paper** button
- `agents_main.py --once` through the **Run Manager** button
- `agents_main.py --once --online` through the **Run Online Manager** button
- `agents_main.py --once --online --llm` through the **Run AI Manager** button
- `online_data_main.py` style FRED/SEC refresh through the **Refresh Online Data** button
- `research_main.py` style research outputs through the **Run Research** button
- `self_optimize_main.py` style evaluation through the **Run Self Optimize** button
- `trained_main.py` through the **Run Trained Backtest** button
- `optimize_main.py` through the **Run Optimizer** button

Safety note: the website only uses the local simulation files. It does **not** connect to IBKR, does **not** require a broker account, and does **not** place real orders.

## Overall Manager Agents

The project includes an Overall Manager workflow. It coordinates several local rule-based agents:

- `MarketDataAgent`: checks whether local market data cache exists and is fresh
- `LocalPaperAgent`: runs one local paper trading decision cycle
- `ResearchAgent`: refreshes performance reports and portfolio allocation
- `RiskAgent`: reviews drawdown, Sharpe ratio, exposure, and allocation limits
- `ReportAgent`: writes the final Manager report
- `NotificationAgent`: optionally sends the Manager report by email
- `LLMReviewerAgent`: optional OpenRouter free-first AI review

Run once:

```powershell
python agents_main.py --once --mode local
```

Windows CMD quick start:

```cmd
run_manager.cmd
```

Outputs:

- `outputs/agent_run_log.csv`
- `outputs/manager_report.md`
- `outputs/notification_log.csv`

## Email Notifications

Email is disabled by default. The program never stores your email password or app password in code.

Set these environment variables in PowerShell before running the manager:

```powershell
$env:EMAIL_ENABLED="true"
$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USERNAME="your_email@gmail.com"
$env:SMTP_PASSWORD="your_app_password"
$env:EMAIL_FROM="your_email@gmail.com"
$env:EMAIL_TO="your_email@gmail.com"
$env:SMTP_USE_TLS="true"
```

For Gmail, use a Google app password, not your normal login password. Outlook and other providers can also work if you replace `SMTP_HOST`, `SMTP_PORT`, and credentials with that provider's SMTP settings.

Test email connectivity:

```powershell
python email_test_main.py --send
```

Recommended Windows helper, which uses the bundled project Python and prompts for the password securely:

```powershell
.\scripts\run_email_test.ps1
```

Run the manager with optional email notification:

```powershell
python agents_main.py --once --mode local
```

Run the manager with the same secure email prompt:

```powershell
.\scripts\run_manager_with_email.ps1 -Mode local
```

If `EMAIL_ENABLED` is not true, `NotificationAgent` records a safe `SKIPPED` status and sends nothing.

## 24-Hour Local Daemon

The project includes a local daemon for running the multi-agent team outside Codex. It still uses local paper trading only and does not connect to any broker.

Quick one-time check:

```cmd
run_daemon_once.cmd
```

Start the long-running daemon:

```cmd
run_daemon.cmd
```

PowerShell / Python equivalent:

```powershell
python daemon_main.py --once --mode local
python daemon_main.py --mode local
```

Daemon jobs:

- `daily_local_paper`: after the NYSE close, runs local paper trading once per trading day; if the daemon was offline and the virtual account is behind the latest completed trading day, it can catch up once outside regular market hours
- `daily_risk_check`: runs a lightweight risk check once per local day
- `weekly_research`: after a market close, refreshes research and self-optimization once per week
- `daily_online_scan`: in `--mode online` or `--mode ai`, scans public projects once per day

Force a single job for testing:

```powershell
python daemon_main.py --once --force-job daily_risk_check
python daemon_main.py --once --force-job daily_online_scan --mode online
```

Daemon outputs:

- `outputs/agent_status.json`
- `outputs/dashboard_status.csv`
- `logs/daemon.log`
- SQLite table: `daemon_runs`

Stop the daemon with `Ctrl+C`. For true 24-hour operation on Windows, run `run_daemon.cmd` in a terminal you keep open, or add it later to Windows Task Scheduler.

### Manager Modes

The Manager supports three explicit modes:

```text
local   = local files only, no internet LLM work
online  = local mode + public GitHub project scan
ai      = online mode + OpenRouter LLM review
```

Commands:

```cmd
run_manager.cmd
run_online_manager.cmd
run_ai_manager.cmd
```

Manual commands:

```powershell
python agents_main.py --once --mode local
python agents_main.py --once --mode online
python agents_main.py --once --mode ai
```

### Online Practice Mode

The online mode only reads public internet data. It does not connect to IBKR, does not use a brokerage account, and does not place orders.

Run once with public GitHub project scanning:

```powershell
python agents_main.py --once --mode online
```

Windows CMD quick start:

```cmd
run_online_manager.cmd
```

Additional online output:

- `outputs/online_research_projects.csv`
- `outputs/online_portfolio_allocation.csv`
- `outputs/online_portfolio_allocation_summary.csv`

The current online agent reads public GitHub metadata for selected quant and agent-framework projects. It is intended for research practice and project discovery.

Optional online quant dependencies:

```powershell
python -m pip install -r requirements-online.txt
```

`requirements-online.txt` adds Riskfolio-Lib and skfolio. On Windows, Riskfolio-Lib may require Windows Long Path support because it pulls large scientific/Jupyter dependencies. If the optional install fails, the project still runs and automatically falls back to PyPortfolioOpt or inverse-volatility allocation.

GitHub's unauthenticated API can be rate limited. To raise the limit without storing secrets in code, set an environment variable before running:

```powershell
$env:GITHUB_TOKEN="your_token_here"
python agents_main.py --once --online
```

If no token is provided, the agent still runs and writes a fallback candidate list when GitHub rate limits the request.

### OpenRouter Free-First AI Manager

The optional LLM Agent uses OpenRouter and defaults to:

```text
openrouter/free
```

This asks OpenRouter to route to a free available model. Free model availability and rate limits are controlled by OpenRouter.

Set the API key as an environment variable. Do not save it in code:

```cmd
setx OPENROUTER_API_KEY "your_key_here"
```

Close and reopen CMD after `setx`, then run:

```cmd
run_ai_manager.cmd
```

Manual command:

```cmd
python agents_main.py --once --mode ai
```

Optional model override:

```cmd
setx OPENROUTER_MODEL "openrouter/free"
```

AI output:

- `outputs/llm_manager_review.md`

Safety rules:

- LLM Agent only reads local CSV/report outputs and public project metadata
- It does not connect to IBKR
- It does not place orders
- It must not recommend leverage, short selling, or options
- It is a simulation/research reviewer only

## Research Tools

The project includes optional research helpers inspired by widely used open-source quant libraries:

- `QuantStats`: professional performance metrics and HTML reports
- `pandas_market_calendars`: NYSE trading-day, holiday, and early-close calendar
- `Riskfolio-Lib`: optional online-first risk parity allocation when installed
- `PyPortfolioOpt`: long-only portfolio allocation suggestions
- `skfolio`: optional future portfolio model-selection experiments

Run the research update:

```powershell
python research_main.py
```

Research outputs:

- `outputs/local_performance_report.html`
- `outputs/local_performance_metrics.csv`
- `outputs/performance_report.html`
- `outputs/performance_metrics.csv`
- `outputs/portfolio_allocation.csv`
- `outputs/portfolio_allocation_summary.csv`
- `outputs/online_portfolio_allocation.csv`
- `outputs/online_portfolio_allocation_summary.csv`

Portfolio allocation rules:

- Long-only
- No leverage
- No short selling
- Single-symbol target weight capped by `max_position_pct`
- Any unused allocation remains as cash
- Riskfolio-Lib is tried first when installed
- PyPortfolioOpt is the first fallback
- Inverse volatility is the final fallback

These reports are decision-support tools only. They do not change the trading account by themselves and do not place orders.

## Market Calendar Safety

The project integrates `pandas_market_calendars` for NYSE trading sessions. It is used by the safety layer to detect:

- Regular trading days
- Market holidays
- Early-close sessions
- Current regular trading hours

If the dependency is unavailable, the program falls back to the built-in NYSE holiday approximation.

## Self Optimization

Run the autonomous self-evaluation workflow:

```powershell
python self_optimize_main.py
```

It generates:

- `outputs/strategy_variant_scores.csv`
- `outputs/strategy_variant_report.md`
- `outputs/adaptive_strategy_profile.json`
- `outputs/adaptive_strategy_profile.csv`
- `outputs/github_project_candidates.csv`
- `outputs/github_project_discovery.md`
- `outputs/self_optimization_actions.csv`
- `outputs/self_optimization_report.md`

The workflow compares strategy variants, searches public GitHub repositories for useful future integrations, and writes prioritized next actions. It is still research-only and never places orders.

The adaptive strategy profile is a gated candidate configuration. Local paper trading does not apply it by default. To test it in local simulation:

```powershell
python local_paper_main.py --once --use-adaptive-profile
```

If the health gate is still `OBSERVE_ONLY`, the profile is only reported and not applied.

## Local Database

The project now uses a CSV + SQLite dual-write storage model.

CSV outputs are still preserved in:

```text
outputs/
```

SQLite is written to:

```text
data/app.db
```

The database is local-only and ignored by Git. It is used for longer-term storage and future website queries.

Current SQLite tables include:

- `accounts`
- `account_history`
- `positions`
- `orders`
- `trades`
- `decisions`
- `run_logs`
- `agent_runs`
- `notifications`
- `backtest_reports`
- `portfolio_allocations`
- `generic_frames`

The website shows a **Database Status** table with row counts. Existing CSV workflows remain compatible.

## Parameter Optimization

Run a lightweight parameter sweep:

```powershell
python optimize_main.py
```

The optimizer tests combinations of:

- Fast / slow moving averages
- RSI threshold
- Stop loss
- Take profit
- Maximum holding period

Optimization outputs:

- `outputs/optimization_results.csv`
- `outputs/optimization_top10.csv`

This is intended for research only. The best historical parameter set is not a promise of future performance.

## Walk-Forward Validation

Run rolling train/test validation:

```powershell
python walk_forward_main.py
```

The validator selects parameters on a training window, then tests the selected parameters on the next unseen window. This helps detect overfitting before a parameter set is trusted in the local paper trading workflow.

Walk-forward outputs:

- `outputs/walk_forward_results.csv`
- `outputs/walk_forward_top20.csv`
- `outputs/walk_forward_summary.csv`
- `outputs/walk_forward_report.md`

The website also has a **Run Walk-Forward** button. The research workflow runs walk-forward before refreshing the strategy health score.

## Trained Candidate Backtest

After parameter optimization, the current trained candidate is:

```text
MA30 / MA60
RSI < 60
Stop loss: -5%
Take profit: +30%
Max holding period: 30 trading days
```

Run it without overwriting the baseline backtest:

```cmd
run_trained_backtest.cmd
```

Manual command:

```powershell
python trained_main.py
```

Outputs are written to:

```text
outputs/trained/
```

This candidate is research-only. It was selected from historical data and must be monitored for overfitting.

Design inspiration:

- `backtesting.py`: simple order, fill, and position separation
- `pyfolio` / `empyrical`: equity curve, drawdown, and Sharpe-style reporting
- `PyPortfolioOpt`: portfolio-level exposure and allocation awareness
- `vectorbt`: future-friendly structure for parameter sweeps

## Backtesting

Run the offline backtest:

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Backtest outputs:

- `outputs/trade_log.csv`
- `outputs/backtest_report.csv`
- `outputs/equity_curve.png`

If the Windows `python` command points to the Microsoft Store placeholder, select a real Python 3.12 interpreter in VS Code before running the project.

## Market Data

The project uses `yfinance` for historical daily data.

If `yfinance` fails because of network issues, the data loader falls back to the Yahoo Chart historical endpoint and caches data in:

```text
data_cache/
```

Generated data and output folders are ignored by Git.

## Optional IBKR Paper Trading

The IBKR module is kept for future use, but it is not the default path.

Only this command attempts to connect to IBKR:

```powershell
python paper_main.py --once
```

Default IBKR safety configuration:

```python
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7497
IBKR_CLIENT_ID = 1
DRY_RUN = True
ALLOW_LIVE_TRADING = False
```

IBKR safety rules:

- Only accounts starting with `DU` are accepted as IBKR Paper Accounts
- Non-paper accounts cause the program to stop immediately
- `ALLOW_LIVE_TRADING=True` is rejected
- `DRY_RUN=True` prints and logs orders without calling `placeOrder`
- Orders can only be sent after manually setting `DRY_RUN=False`
- Orders still require a verified IBKR Paper Account
- Market orders use `outsideRth=False`
- Only `STK` contracts are allowed
- Sell quantity cannot exceed current long holdings

IBKR-related outputs:

- `outputs/paper_order_log.csv`
- `outputs/paper_trade_log.csv`
- `outputs/paper_risk_log.csv`
- `outputs/paper_position_state.csv`

## TWS / IB Gateway Setup

TWS Paper Trading:

1. Start Trader Workstation.
2. Log in with Paper Trading.
3. Confirm the account number starts with `DU`.
4. Open `Global Configuration -> API -> Settings`.
5. Enable `Enable ActiveX and Socket Clients`.
6. Paper TWS usually uses port `7497`.
7. API order submission must be enabled before sending paper orders.

IB Gateway Paper Trading:

1. Start IB Gateway.
2. Log in with Paper Trading.
3. Paper Gateway commonly uses port `4002`.
4. If using Gateway, change `IBKR_PORT` to `4002`.

## Recommended Daily Workflow

Local paper trading:

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python local_paper_main.py --once
```

Generate the dashboard:

```powershell
python dashboard.py
```

Run the web app:

```powershell
python web_app.py
```

Open `http://127.0.0.1:5000` in your browser.

Refresh research reports:

```powershell
python research_main.py
```

Run the Overall Manager:

```powershell
python agents_main.py --once
```

Run the online practice manager:

```powershell
python agents_main.py --once --online
```

Run the AI Manager with OpenRouter free-first mode:

```cmd
run_ai_manager.cmd
```

Run parameter optimization when needed:

```powershell
python optimize_main.py
```

Run the trained candidate backtest:

```cmd
run_trained_backtest.cmd
```

Install a Windows daily scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_daily_local_paper_task.ps1
```

The default scheduled run time is `06:30`, which is intended to run after the US market close from a China timezone workflow.

Optional IBKR Paper Trading:

```powershell
cd C:\Users\rog\Documents\GPTprogram\us_paper_backtester
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python paper_main.py --once
```

## Important Notes

Backtesting and local paper trading are simulations. They do not place real orders and do not use real money.

The local paper trading mode can run without any brokerage account.

The IBKR module is optional and remains protected by:

```python
DRY_RUN = True
ALLOW_LIVE_TRADING = False
```

This project is for research and educational use only. It is not financial advice.
