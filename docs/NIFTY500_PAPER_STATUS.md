# NIFTY 500 paper automation and PC status

New paper automation settings and the Technical Scanner default to NIFTY 500.
The paper tab's Start button explicitly requests NIFTY 500. Scanner handoff
continues to restrict entries to selected matching stocks and their strategy;
the backend verifies membership and re-scans them against current data.
Without a stock filter, automation scans the full NIFTY 500 universe and only
admits matching candidates that pass validation, fresh-quote and risk checks.
The scanner's result ranking limit does not truncate the input universe.

Previously saved universes and stock/strategy filters remain visible for review.
An existing running session is not changed by updating the code. Stop automation
before changing its scope, then Start in the paper tab to use NIFTY 500, or run a
NIFTY 500 scan and use Start paper trading selected stocks. This preserves the
operator's control over entries and does not close existing positions.

The left panel shows the paper universe, stock scope and selected strategies.
These are configured targets, not proof that a strategy passed validation or
opened a position. Review the latest cycle and each position's strategy ID and
source scan ID for execution evidence.

## Check the actual running PC backend

After updating the release, leave the original server PowerShell window open.
In a second Windows PowerShell window, use the same launcher path used to start
that release, with `-CheckPaper` appended. If `$tfLauncher` is already set:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $tfLauncher -CheckPaper
```

This reads the local admin key from the selected data root, makes authenticated
GET requests only to `127.0.0.1`, and prints a limited JSON report. It does not
create keys, open the runtime lock, change settings, start automation, or submit
orders. Network proxies and redirects are disabled. Keep using the same
`-DataRoot` and `-Port` if the server was launched with custom values.

It checks verified storage, the NIFTY 500 scope, worker heartbeat, quote monitor,
strategy exit monitor, Kite authentication, entry blockers and paper-only gates.
During the weekday entry window it also requires current-catalog full-universe
validation and a fresh sample market quote. A worker scanning a large universe
is explicitly reported as a cycle in progress; a stale heartbeat still requires
attention and is not treated as evidence of healthy execution. Per-stock quote freshness and
strategy promotion are still enforced at entry, not established by the sample.

- `running`: the queried operational checks passed and automation is ON.
- `off`: those infrastructure checks passed but entries have not been armed.
- `waiting_for_market`: automation is ON outside the weekday entry window.
- `needs_attention`: inspect the `issues` list; no settings have been changed.
- `backend_check_failed`: an endpoint rejected or could not complete the check.
- `backend_unavailable_or_invalid`: the local server could not be reached or
  returned an invalid response. Check its original PowerShell window.

These are snapshots, not guarantees of future execution or profit. No position
is expected until an eligible signal, successful validation and risk approval
coincide during market hours. Exchange holidays and stale individual quotes can
still prevent entry. Use `-CheckKite` separately to diagnose credential loading.

The cloud development workspace cannot inspect a server on the owner's PC.
Only the PC diagnostic output can establish the state of that running instance.
