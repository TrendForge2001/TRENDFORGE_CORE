# Research runtime and report recovery

The November 8 incident showed process restarts without a new deployment and
sustained use of the free service's observed 0.15 CPU limit. Sampled memory stayed
below the reported 512 MiB limit; those samples do not prove or exclude a brief
memory spike. The exact reason for each platform restart was not established.
The screenshot's connection-level 429 is distinct from the research queue's
explicit 429 response. A successful deployment/health probe alone does not prove
that a large backtest completes or that an ephemeral filesystem survives restart.

## Changes

- EMA/pivot simulation uses causal dictionary rows and the same evaluation rules,
  avoiding repeated pandas slicing and strategy-catalog reconstruction per bar.
  Long/short fills, partial exits, costs and equity observations are compared
  against the previous evaluator path. No trading rules or account limits change.
- History is fetched and enriched in bounded batches; only required indicator
  columns are retained. Large cloud previews exceeding 150,000 estimated candle
  rows are rejected before fetching, with instructions to use the PC. Accepted
  runs keep their entire requested universe; no silent stock truncation occurs.
- History, indicator calculation, simulation bars and report generation have
  separate progress counters and a last-update timestamp. Batch IDs are exported.
  Interrupted runs stay interrupted and are never replayed automatically.
- The canonical Streamlit entrypoint is `streamlit_app.py`, outside the legacy
  `pages` directory. Cold deep links and reconnections therefore execute the
  main navigation and access gate before the selected page. Standalone and
  unified launch configurations use the same entrypoint.

## Permanent PC reports

The owner selected the PC for durable reports. Continue using the existing
DataRoot and paper ledger; never replace or merge existing books to upgrade.
Start the existing PC launcher and open `http://127.0.0.1:10000/app/` (or the
configured local port). Keep the PC awake while research or paper monitoring runs.

Each completed PC research batch writes an immutable folder under
`<DataRoot>/reports/research/`. Its files are `report.csv`, `report.xlsx` when
available, and `batch.json` containing the recorded request, metadata and report.
Files are flushed, checksummed and published together before marking the batch
complete. A filesystem failure is explicit; an older report is never overwritten.
On PC startup, valid files restore missing research indexes without fetching
market data, rerunning a strategy or changing paper positions. Invalid/conflicting
backups are counted and left untouched. Keep an external backup of the DataRoot.

## Preserve reports still present on Render

Render remains the free read-only trading workspace. Research data there is
**temporary**. A server-side process replacement, redeploy or service lifecycle
can remove its files. The cloud does not automatically write to a sleeping PC.

Before another deployment, download and run `scripts/windows/Save-CloudReports.ps1`
on Windows. It needs no Python installation. It requests the **cloud Admin API
Key in a hidden local prompt**, reads only existing report GET endpoints and
saves completed reports in the PC archive layout. Never put keys in chat or on
command lines. For an existing custom DataRoot, pass that same `-DataRoot` value.

After installing the PC runtime, the Python-backed companion also supports
continuous copying while the PC stays awake:

```powershell
.\scripts\windows\Save-TrendForgeReports.ps1 -Watch
```

To restore a downloaded **batch backup JSON**, use:

```powershell
.\scripts\windows\Save-TrendForgeReports.ps1 -Files 'C:\Downloads\trendforge_batch-example.json'
```

Then restart the PC app to load newly copied files. A trade CSV/Excel copy can
preserve exported trades, but the earlier one-row batch-status CSV contains no
fills and cannot reconstruct them. Reports erased from an old ephemeral instance
require a surviving database or downloaded copy for recovery; a re-run is a new
result, not restoration of the original evidence.

## Verification

Besides semantic/unit tests, the release gate starts the real unified application
with synthetic 100-stock, 500-bar history. Browser acceptance opens a cold Reports
URL, verifies sign-in and six-page navigation, runs a backtest, downloads its CSV,
checks API liveness during work, then restarts the application after removing only
the test's research indexes. The original report must reappear from PC files.
This tests the application lifecycle without broker requests or real orders.
