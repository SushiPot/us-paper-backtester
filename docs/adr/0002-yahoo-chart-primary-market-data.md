# ADR 0002: Prefer Yahoo Chart for Routine Market Data Refresh

## Status

Accepted

## Context

Routine runs were hitting yfinance rate limits while refreshing many symbols. Once yfinance was rate-limited, repeated requests in the same run slowed the program and still failed.

## Decision

Use Yahoo Chart as the default historical daily market data source. yfinance remains available by setting `MARKET_DATA_PRIMARY_SOURCE=yfinance`, but a detected yfinance rate limit causes the rest of that run to skip yfinance and use Yahoo Chart instead.

## Consequences

- Routine cache refreshes make fewer failing yfinance requests.
- The cache warmup flow can continue through a symbol list after a yfinance rate limit.
- yfinance remains available for users who explicitly want it first.
- Market data behavior needs regression tests because source ordering and same-run fallback are operationally important.
