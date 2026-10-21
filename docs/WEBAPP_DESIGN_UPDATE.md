# Trading workspace design update

The existing Streamlit webapp now uses a compact terminal layout with a clear
research/paper context, restrained indigo accents, tabular numbers, consistent
panels and responsive spacing. This release updates the deployed UI code;
framework migration remains a separate project.

## Interaction model

- Liquide inspiration: clear research hierarchy and concise context before data.
- Kite inspiration: dense watchlists, fast company/symbol search, sector filters
  and a direct transition from stock selection to chart/detail.
- Streak inspiration: keep strategy scanning/backtesting and saved results in
  one focused technical workspace with explicit run actions.

The five current navigation entries remain Watchlist, Portfolio, Fundamentals,
Technicals and Corporate Actions. Portfolio and Technicals use active-view
controls so hidden screens do not execute requests.

The watchlist displays constituent coverage and quote availability separately.
CSV membership overrides are tucked into an expandable source section. Empty
search results are explicit. Missing prices remain missing; the design never
substitutes fabricated prices. Screenshots used for local design inspection
are generated with clearly labelled sample fixtures, not production data.

## Status and access

The workspace bar displays research/paper context and the render time in IST.
It does not claim that the exchange is open, trading is enabled, or the backend
is healthy. The sidebar says `Not probed` for API health and `Key configured`
for supplied credentials; successful authentication requires a backend response.
Portfolio and paper portfolio aliases now require authentication in production.
The existing sign-in gate remains in place.

Visible keyboard focus, reduced-motion support, responsive bar wrapping and
tabular financial values improve navigation and readability. Native Streamlit
tables retain horizontal scrolling on narrow screens.

## Export correction

R71.5 now downloads a JSON validation report using the existing admin header.
The UI no longer expects a token that the runtime never generates, or labels
JSON bytes as an Excel workbook. The URL does not carry an export secret.

## Future deployment target

For the eventual Streamlit replacement, use Next.js/TypeScript for the UI,
FastAPI for domain APIs, a server-side credential boundary and durable database
storage. Render Node beside the existing Render API is a practical initial
deployment option. Evaluate Vercel for the frontend if background scans remain
in separately hosted workers. Do not move long-running scans into frontend
request handlers. Migration requires its own feature-parity and cutover checks.
