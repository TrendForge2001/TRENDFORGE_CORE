# R71.3 — Source-Excel fundamental research conditions

Reference-only implementation. This page records how two user-provided
workbooks informed the research criteria. **Neither file is loaded into
TrendForge at runtime, shipped to Render, modified, or treated as a
financial-data provider.**

## Source workbooks inspected (19 Oct 2026)

1. `Equity research-1.xlsx`
   - `Relative video!J12:L29`: ordered aggressive and conservative
     priorities (18 aggressive metrics, 17 conservative).
   - `Bank!D3:J3` and `Bank!L2`: banking measures (NIM, CASA, ROE,
     ROCE, Net PAT / Net Profit, SLR; qualitative net-NPA/cost-of-funds
     considerations).
   - `Pharma!K3:AL3`: pharma financial, operational, growth, leverage
     and promoter/pledge observations.
   - `MSCI !G1:L12`: conceptual factor categories (value, quality,
     momentum, volatility, growth and liquidity). Not a numeric scoring
     prescription.
2. `Stock selection 10 oct 26.xlsx`
   - `Final!A1:R1`: current and historical financial *column names*
     including growth five-year comparisons, ROCE/ROE five-year,
     P/E, margins, debt/equity and changes in promoter holdings.
   - `Final!A2:T99` has selected company observations/notes as of the
     workbook date; **not live market data or training labels**.
   - The workbook includes a NIFTY 500 symbol reference sheet, which
     is not an authoritative runtime universe.

## Profile ordering

Aggressive: Operating profit margin → PEG → ROE 3Y → ROCE 3Y →
Sales growth 3Y → EPS 3Y → Profit growth → PAT → EV/EBITDA →
Inventory turnover → ROA 3Y → Interest turnover → Promoter holding →
Change in promoter holding → Current ratio → Quick ratio →
Interest coverage → Debt/equity.

Conservative: Debt/equity → Interest coverage → Quick ratio →
Current ratio → Promoter holding → Pledged promoter holding % →
Change in promoter holding → ROA 3Y → EV/EBITDA →
Inventory turnover → Profit growth → EPS → Sales growth 3Y →
ROCE 3Y → ROE 3Y → PEG → Operating profit.

Ordering is ordinal only. The Excel does **not** specify general
numeric quality cutoffs for every listed metric, weighting coefficients,
backtested impact or a universally valid score. R71.3 does not invent
these values.

## Code and behavior

- `config/reference_fundamental_conditions.py` owns a small **static
  reference catalogue** and source trace. There are no company observations,
  signals or Excel-dependent formulas in code.
- `ContractedFundamentalEngine.evaluate` appends
  `metrics.source_reference_profiles` containing observation **coverage**:
  available/missing metric keys, completeness count and source-profile
  version. The output expressly says `quality_score=null`,
  `pass=null`, and `affects_execution_eligibility=false`.
- The canonical `FundamentalEngine` remains the only numeric mandatory
  quality scorer. Its 8 required fields, threshold tiers, existing 53
  maximum points, R69.4 evidence requirements and mandatory gates are
  unchanged. No hardcoded stock selection or current-price values.
- Staging Streamlit `Data → Fundamentals` displays the two priority
  lists and any matching observed metrics from a previously inspected
  symbol; these are *not* verified source-specific financial scores.
- FinEdge observations remain **read-only unverified JSON** until
  source date, accounting period, field definition, units and company
  identity have been separately checked. FinEdge responses are **not**
  silently mapped into three- or five-year fields and cannot directly
  make a stock execution eligible.

## Explicit data caveats

- Current ROE is not the same as ROE 3Y average; current ROCE is not
  ROCE 3Y or ROCE 5Y.
- One-year sales/profit growth is not three-/five-year CAGR without
  supporting calculation details.
- EPS level, trailing 12M EPS, and three-year EPS growth are distinct.
- EV/EBITDA spelling `EVEBDITA` in the workbook was normalized only
  as a research field label, **not** as a new threshold.
- Banking uses sector-specific NIM, CASA, asset-quality and cost-of-funds
  data; standard corporate debt/equity scores cannot replace bank-specific
  analysis without a reviewed sector model.

## Before enabling a source-profile numeric score

Explicitly approve metric definitions, directions, weights, absolute or
peer-relative pass criteria, sector exceptions, missing-data policy and
validation periods. Version and backtest the resulting model before making
it eligible for paper or live execution. R71.3 does none of this.
