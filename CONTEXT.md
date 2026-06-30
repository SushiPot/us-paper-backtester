# Project Context

This glossary records the domain language for the US Paper Backtester. It is a shared vocabulary for humans and coding agents, not an implementation spec.

## Terms

**Local Paper Account** - A simulated trading account that uses virtual cash, virtual positions, and historical market prices. It never connects to a broker and never places live orders.

**Local Paper Run** - One pass that updates the Local Paper Account for the latest completed US trading day, evaluates risk, and may create simulated orders.

**Market Data Cache** - The local store of historical daily OHLCV bars used by backtests, local paper runs, ranking, and research checks.

**Cache Warmup** - A non-trading maintenance run that gradually fills or refreshes Market Data Cache entries. It does not change positions or account cash.

**Market Data Source** - A network provider used to refresh the Market Data Cache. The project treats Yahoo Chart as the default source and yfinance as an opt-in or fallback source.

**Universe** - The list of symbols the project is allowed to evaluate.

**Required Symbol** - A Universe symbol that should be prioritized when data is missing or stale.

**Watch-Only Symbol** - A Universe symbol that can appear in reports but is not eligible for normal buying decisions.

**Candidate** - A symbol that passed enough checks to be ranked for possible simulated trading.

**No-Trade Explanation** - The reason a run produced no simulated order even though the system evaluated candidates.

**Risk Gate** - A rule that can allow, reduce, or block new simulated buying based on market, macro, benchmark, strategy, or account conditions.

**Health Light** - A dashboard status row that summarizes whether one operational area is OK, needs attention, or is missing data.

**Agent Run** - A coordinated pass through the project's analysis agents.

**Daemon** - The local scheduler that checks whether maintenance or analysis work is due and runs those jobs without human clicks.

**Daemon Job** - One scheduled unit of work, such as Cache Warmup, Local Paper Run, risk check, online scan, or weekly research.

**Run Key** - The date or week identifier that prevents the same Daemon Job from being counted as successfully completed more than once for the same period.

**Online Scan** - A research-only job that can read public internet metadata. It does not trade.

**Standalone Runtime** - The project-local Windows Python environment used when Codex is closed.
