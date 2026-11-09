# PC paper deployment preparation

The owner selected PC paper execution. Render remains read-only. This package
does not access or update a laptop, enable real broker orders, or start paper
automation automatically.

## Account policy

The reviewed PC defaults are in `config/pc_paper_policy.json`:

- Starting capital: INR 100,000; fixed reserve: zero.
- Maximum concurrent positions: three, across strategies.
- Maximum new positions per IST day: six, across strategies. Partial exits do
  not count as new entries. Closing a trade does not free a daily entry slot.
- Existing sizing: 1% risk limit for ordinary entries; staged EMA/pivot entries
  remain capped at 0.5%. Existing 20% per-trade capital cap and 1:2 minimum
  reward/risk remain. These constraints can leave cash unused; zero reserve
  makes the full account available rather than forcing full investment.
- Entry loss limit: 3% of starting capital. Include today's realized net P&L
  and currently marked open P&L. Preserve the existing gross realized-loss
  guard as an additional constraint. Entry stopping does not disable exits.
- For carried positions, open P&L is measured from entry, not reset to the
  previous close. This is a conservative book-based guard, not an audited
  daily mark-to-market return. Fresh quotes and strategy validation still apply.

The daily entry cap and zero reserve follow the owner's choices on 9 November
2026. Existing strategy validation does not prove matching account-level
backtest performance or a profitable live-paper session.

## Installation and first checks

Extract the release ZIP and follow `READ_ME_FIRST.txt`. Install Python 3.12 for
Windows with its `py` launcher. `START_PAPER.cmd` installs the pinned dependencies
on first use and launches the backend on loopback port 10000.

Preserve the existing DataRoot, ledger, proof files and private keys. The default
is `%LOCALAPPDATA%\TrendForgeCore`. Pass `-DataRoot "D:\YourExistingFolder"`
to the start and check scripts when retaining a custom location. Do not point a
new empty book at the old installation or delete recovery proof files.

Save current Kite credentials in `DataRoot\private\kite.env`. No credentials or
existing owner data are included. After the first storage probe, stop with
Ctrl+C and restart with the same DataRoot to verify recovery. Open
`http://127.0.0.1:10000/app/paper_session` using `OPEN_PAPER.cmd` and sign in
with the local private webapp and admin keys. Run `CHECK_KITE.cmd` and
`CHECK_PAPER.cmd`; failures return a nonzero exit code.

Use one runtime and keep the PC awake while it monitors positions. Closing the
browser does not stop the backend; sleep, shutdown or closing the launcher does.
The Render website does not mirror this PC's database or reports. Reports must
be opened in the PC workspace and preserved with its existing backup scripts.

Paper P&L currently excludes brokerage, statutory charges and slippage. Use a
separate cost-adjusted review before judging an edge. This package does not
establish net profitability.

Paper activation is separate from preparing the package: the owner must verify
the local Windows drive, two-boot recovery, current Kite credentials and fresh
quotes, then run validation and explicitly press Start in the PC page. These
checks cannot be certified remotely while laptop-file access is denied.
