# Stock lists on every workspace page

The **Stock list** selector is available above the page controls on all six
workspace pages: Stock Watchlists, Technical Scanner, Kite Backtesting,
Live Paper Trading, Live Kite Session and Reports. The selected list carries
between pages within the signed-in session. The existing NIFTY 500 choice
remains available alongside every list visible in the owner's screenshots.

There are 28 lists/views: Major Indices; Global Indices; Nifty 50; BSE Sensex;
Nifty Next 50; Nifty 100, 200 and 500; Nifty LargeMidcap 250; Nifty Midcap 150
and Midcap Select; Nifty Smallcap 250 and Microcap 250; Bank Nifty; Nifty
FinNifty; Nifty IT, Auto, FMCG, Pharma, Metal and Realty; BSE Bankex; and
NSE F&O Stocks. Sector-grouped views are provided for Nifty 50, BSE Sensex,
Nifty Next 50, Nifty LargeMidcap 250 and NSE F&O Stocks.

## Using a list

- Watchlists displays the selected members, sectors, Kite NSE prices and daily
  changes. Grouped views sort stocks by sector and company.
- Scanner and Backtesting use the selected equity members as their research
  universe. Choosing a list does not start a scan or backtest.
- On any page, enable **Browse list members**, then choose **Load / refresh
  members** to see or search the list. Membership is not fetched automatically
  during paper refreshes. **Use this stock** copies only the selected symbol
  into supervised paper-entry and read-only Kite-preview forms; quantities,
  prices and submission remain explicit form actions.
- Reports and broker/paper account views retain their recorded data and scope.
  The shared browser provides stock lookup without concealing existing trades.
- Major and Global Indices contain curated index-symbol references for browsing.
  They do not represent stock constituents and are not admitted to equity
  scanners/backtests. No global-index prices are manufactured or requested as
  NSE equity symbols.

## Membership sources

Nifty memberships use NSE/Nifty Indices constituent CSVs, including the new
Nifty Next 50 CSV. NSE F&O Stocks uses NSE's permitted-lot-size CSV intersected
with the current NSE EQ security master; this excludes index derivatives and
returns the equity underlyings. Sector enrichment uses NSE NIFTY 500 metadata
when available, with unmapped sectors explicitly shown as Unclassified.

BSE Sensex and Bankex membership uses the public Smart Investing component
tables. This is a secondary reference source, labelled as such. Every member
must map uniquely by normalized company name to NSE NIFTY 500 metadata; Sensex
requires all 30 members, and Bankex uses a bounded 10–30-member sanity range.
Incomplete or ambiguous mappings fail instead of substituting another index.
Prices and equity research use the mapped **NSE listings**, not BSE quotes.

Sources:

- https://nsearchives.nseindia.com/content/indices/ind_niftynext50list.csv
- https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv
- https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
- https://www.smart-investing.in/indices-bse-nse.php?index=SENSEX
- https://www.smart-investing.in/indices-bse-nse.php?index=BANKEX

Runtime caches retain only validated membership snapshots. A failed live refresh
can return the last validated list with a stale flag and its retrieval time;
without a valid snapshot, membership is explicitly unavailable. Grouped views
reuse the underlying base membership. Price requests use batches of at most
500 instruments and preserve missing prices as blank values.

`GET /workspace/stock-lists` exposes the same catalogue without fetching prices
or memberships. Existing `/workspace/watchlist/{name}/constituents` and quote
routes accept the shared catalogue and supported aliases. Research request
validation admits the 26 equity lists/views and rejects the two index-only
reference lists.
