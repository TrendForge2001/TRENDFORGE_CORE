# TrendForge R72.0 — Application Shell & UI/UX Map

## Objective

R72.0 converts the Streamlit staging application from a collection of working pages into one coherent trading/research product shell. The design borrows interaction principles commonly seen in modern broker terminals and research products—compact navigation, information-dense cards, clear state badges, fast scanning, and low visual noise—without cloning another product.

The batch is UI/application-shell work only. Existing scanner, technical, research, portfolio, notification and operations logic remains the source of truth. Production FastAPI is not modified.

## Application structure

| Workspace | Page | Primary job |
|---|---|---|
| Home | Command Center | Core/API health, scanner state, market context and safety status |
| Home | Watchlists | Focused symbol monitoring and operator lists |
| Home | Market-Day Operations | Session readiness and operating controls |
| Trade | NIFTY 500 Scanner | Rank and inspect scanner candidates |
| Trade | Technical Lab | Intraday/swing technical scan and technical backtest |
| Trade | Paper Trading | Simulated positions, risk gates and exits |
| Markets | Market Breadth | Participation and breadth confirmation |
| Markets | Market Regime | Trend/risk regime context |
| Markets | Sector Strength | Sector leadership and confirmation |
| Research | Weekend Research | Completed-candle research and stock selection |
| Research | Backtesting | Historical strategy simulation |
| Research | Fundamentals | Fundamental evidence, coverage and scoring inputs |
| Research | News Intelligence | News/sentiment evidence |
| Research | Big Shark Activity | Institutional/large-holder confirmation |
| Research | Corporate Actions | Dividend/split/bonus context |
| Portfolio | Portfolio | Holdings and exposure |
| Portfolio | P&L Statement | Realized/unrealized result view |
| Portfolio | Performance | Return and trading-effectiveness metrics |
| Operations | Scan History | Run history and traceability |
| Operations | Notification Center | Alert readiness/policy/delivery |
| Operations | Scheduler Reliability | Missed-run and scheduler reliability controls |
| Operations | System & Access | API configuration, access and diagnostics |

## Design system

The shell uses a midnight terminal palette with a cobalt primary action color, emerald positive state, amber caution state and red risk state. Information density is intentionally high, but spacing, borders and typography separate decision layers.

Shared UI behavior is centralized in `webapp/ui.py`, so every existing page inherits the same styling without duplicating CSS. The sidebar exposes connection/admin/mode state, and the session can be explicitly locked from any page.

## Safety posture

The UI identifies the current surface as Research / Paper. R72.0 does not enable live trading, change execution eligibility, relax risk gates, bypass admin authentication, or change production FastAPI.

## Acceptance contract

- 22 existing pages remain reachable.
- Exactly one default page: Command Center.
- Navigation is grouped into six operator workflows.
- The access gate still renders before navigation.
- Production admin key handling remains session-scoped.
- Staging continues to target the existing production API through `TRENDFORGE_API_URL`.
- The Streamlit service remains a separate Render service/branch from production FastAPI.
