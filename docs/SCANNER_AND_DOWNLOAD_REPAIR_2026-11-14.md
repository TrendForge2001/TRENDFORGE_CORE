# Scanner choices and report downloads

The owner requested removal of all older scanner choices on 14 November 2026.
Every current Scanner/Backtesting selector now offers only the approved weekly
EMA50/100 gap recovery with Volume EMA30 and yearly Floor R2. Empty horizons are
not displayed. Old browser selection values are reset before rendering. The
backtesting-period and stock-list dropdowns remain. Strategy condition/reference
tables describe the current choice. Historical definitions, saved reports,
explicit authenticated historical API compatibility and existing exit lineage
are retained; no database rows, positions or reports are deleted.

The supplied screenshot shows failed dynamic import of
`DownloadButton.Cfu0gSfV.js`. That filename exists in the pinned Streamlit
package, but the failed request was not found in the queried application logs.
The exact browser/network fetch failure was therefore not independently
identified. CSV/Excel and backup/paper downloads on the active pages now use
native HTML download links, rendered through the already-loaded Markdown
component. They do not load Streamlit's DownloadButton JavaScript widget.

Files remain behind the existing page sign-in and backend authorization. Native
links contain only the authorized file bytes and escaped metadata; no API key
or server credential is included and no public report endpoint is introduced.
Existing report checksum verification is retained. Downloads cause no app rerun.

Browser acceptance deliberately blocks the DownloadButton bundle, completes a
weekly research report, downloads CSV/Excel/JSON and compares their checksums
and identity with the saved batch. It then restarts the isolated fixture and
verifies archived report recovery. The fixture uses artificial observations,
temporary storage and no broker client. Legacy intraday backtests are exercised
through the authenticated compatibility API, not reintroduced as UI choices.

Backend defaults are now separate from display choices so existing authenticated
API callers and monitors retain their release behavior. The release security
check also required opentelemetry-api 1.45.2 and soupsieve 4.0.0; both Linux and
Windows dependency locks use those versions without advisory exemptions.
