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

Buy conditions:

- MA20 crosses above MA60
- RSI(14) is below 70
- Current volume is above the 20-day average volume

Sell conditions:

- MA20 crosses below MA60
- Stop loss: -8%
- Take profit: +20%
- Holding period exceeds 30 trading days

Risk and position rules:

- Initial virtual cash: 10,000 USD
- Maximum position size: 20% of account equity
- Maximum simultaneous positions: 5
- No leverage
- No short selling
- No options
- Daily loss limit: 2%
- Maximum account drawdown: 10%

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
- Simulates 0.05% slippage by default
- Simulates commission at 0.005 USD per share, minimum 1 USD
- Allows only one order decision per run by default

Local paper trading outputs:

- `outputs/positions.csv`
- `outputs/virtual_account.csv`
- `outputs/account_history.csv`
- `outputs/paper_order_log.csv`
- `outputs/paper_trade_log.csv`
- `outputs/decision_log.csv`
- `outputs/run_log.csv`
- `outputs/local_paper_report.csv`
- `outputs/local_equity_curve.png`

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
- Equity curve
- Recent decisions
- Recent orders
- Recent trades

Open `outputs/dashboard.html` in your browser after generation.

## Web App

Windows CMD quick start:

```cmd
run_web.cmd
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

The web app shows the same local paper trading account state in a browser:

- Current equity and virtual cash
- Total return, max drawdown, Sharpe ratio, and open positions
- Equity curve
- Current positions
- Recent decisions, orders, and trades
- Optimization top 10 results

The web app can run:

- `local_paper_main.py --once` through the **Run Local Paper** button
- `agents_main.py --once` through the **Run Manager** button
- `agents_main.py --once --online` through the **Run Online Manager** button
- `research_main.py` style research outputs through the **Run Research** button
- `optimize_main.py` through the **Run Optimizer** button

Safety note: the website only uses the local simulation files. It does **not** connect to IBKR, does **not** require a broker account, and does **not** place real orders.

## Overall Manager Agents

The project includes an Overall Manager workflow. It coordinates several local rule-based agents:

- `MarketDataAgent`: checks whether local market data cache exists and is fresh
- `LocalPaperAgent`: runs one local paper trading decision cycle
- `ResearchAgent`: refreshes performance reports and portfolio allocation
- `RiskAgent`: reviews drawdown, Sharpe ratio, exposure, and allocation limits
- `ReportAgent`: writes the final Manager report

Run once:

```powershell
python agents_main.py --once
```

Windows CMD quick start:

```cmd
run_manager.cmd
```

Outputs:

- `outputs/agent_run_log.csv`
- `outputs/manager_report.md`

### Online Practice Mode

The online mode only reads public internet data. It does not connect to IBKR, does not use a brokerage account, and does not place orders.

Run once with public GitHub project scanning:

```powershell
python agents_main.py --once --online
```

Windows CMD quick start:

```cmd
run_online_manager.cmd
```

Additional online output:

- `outputs/online_research_projects.csv`

The current online agent reads public GitHub metadata for selected quant and agent-framework projects. It is intended for research practice and project discovery.

GitHub's unauthenticated API can be rate limited. To raise the limit without storing secrets in code, set an environment variable before running:

```powershell
$env:GITHUB_TOKEN="your_token_here"
python agents_main.py --once --online
```

If no token is provided, the agent still runs and writes a fallback candidate list when GitHub rate limits the request.

## Research Tools

The project includes optional research helpers inspired by widely used open-source quant libraries:

- `QuantStats`: professional performance metrics and HTML reports
- `PyPortfolioOpt`: long-only portfolio allocation suggestions

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

Portfolio allocation rules:

- Long-only
- No leverage
- No short selling
- Single-symbol target weight capped by `max_position_pct`
- Any unused allocation remains as cash

These reports are decision-support tools only. They do not change the trading account by themselves and do not place orders.

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

Run parameter optimization when needed:

```powershell
python optimize_main.py
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
