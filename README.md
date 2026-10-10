# TrendForge Core

TrendForge is a modular market-analysis and stock-scanning foundation.

## Source of truth

This repository is reconstructed strictly from the audited TrendForge ZIP baseline. No functionality from earlier TrendForge repositories is used.

## Current architecture

- `indicators/` — technical indicator pipeline
- `scanner/` — scanning rules and scoring
- `engines/` — market, sector, fundamental, technical, price-action, risk and signal engines
- `providers/` — market-data providers
- `database/` — persistence layer
- `backtest/` — backtesting components
- `execution/` — order/portfolio components
- `core/` — orchestration

The reconstruction goal is a coherent, testable engine with consistent data contracts between these layers.


## Python runtime

Production uses Render's native Python runtime and is pinned by the root
`.python-version` file to the Python 3.12 release line. Render resolves the
latest available 3.12 patch release for each deploy.

GitHub Actions continues to test both Python 3.11 and 3.12 for compatibility,
while Python 3.12 is the production deployment target. A Render
`PYTHON_VERSION` environment variable, if configured manually, takes
precedence over `.python-version` and should therefore be left unset unless an
intentional override is required.

The production health endpoint exposes
`deployment.python_version` so the deployed interpreter can be verified after
each release.
