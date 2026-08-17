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
