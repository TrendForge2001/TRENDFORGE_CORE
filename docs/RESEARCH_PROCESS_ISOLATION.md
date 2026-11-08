# Backtest connection failure and missing scan reports

Render recorded five health-check timeouts after release aae41b9 on
8 November 2026 (15:12–18:11 IST). CPU samples reached the service's observed
0.15-CPU limit; sampled memory stayed below 512 MiB. These events establish
health-check failure, rather than an access-token rejection or proven OOM.

Cloud research now runs one job at a time in a separate Python process. The
web server only launches/monitors the worker and reads committed SQLite status.
Workers use the same strategy, account-capital, costs and report-validation
code as local research. They construct Kite-only historical data adapters,
disable live/paper execution, limit numerical-library threads, and run at lower
Linux scheduling priority. A crashed worker records a failed batch without
terminating the website. Shutdown terminates the child; interrupted jobs are
never replayed automatically. Jobs have a 30-minute limit.

The Reports page shows the actual storage source, plus independent buttons for
the latest completed scan and backtest. Starting/failing a backtest cannot remove
a completed scan. A Render website cannot read a PC's database merely because
the PC has connected storage. There is no PC synchronization connection in this
application. No laptop access is necessary for this repair.

An owner-supplied scanner Excel workbook can recover its evidence using
`services.research_recovery.scan_workbook_batch`. It preserves the original
Excel bytes and records recovery provenance. A regenerated CSV uses the cell
precision stored by Excel and receives a new checksum. It is scanner evidence,
not a trade report. Workbook text is never executed. The bounded, optional
operator-managed `TRENDFORGE_REPORT_RECOVERY_GZIP_B64` seed restores a completed
snapshot idempotently after server replacement. Its contents stay outside Git.
This recovery seed does not retain future reports.

The current free Render filesystem remains temporary. The optional proposal
`deploy/render.research-persistent.yaml` attaches a 1-GB disk to the existing
service, stores SQLite and immutable report archives under `/var/data`, and
retains read-only cloud execution. It is not applied by the active `render.yaml`.
At the Render prices checked on 8 November 2026, the minimum paid compute plus
this disk is approximately USD 7.25/month before usage and taxes. Applying this
proposal needs approval of its actual Render adoption plan and cost. A disk
requires a brief deployment interruption and a single service instance.
Existing broker/admin credentials must be preserved, never copied into Git.
Restart recovery stays unconfirmed until a report survives an actual restart.

Acceptance coverage uses real subprocesses, worker crashes, snapshot recovery,
and a real browser against synthetic data. The browser runtime is constrained
to 0.15 CPU and 512 MiB without swap. It runs a 100-stock daily backtest and a
100-stock, 1,125-bar intraday EMA 20/50 bearish backtest while probing liveness
with a two-second deadline, then checks report downloads and archive recovery.
Synthetic acceptance verifies software behavior; it does not establish a
strategy's trading edge or validate a live broker candle response.

References: https://render.com/docs/disks,
https://render.com/docs/compute-plans, https://render.com/pricing.
