# R70.1 — Local storage foundation

This release is **opt-in**: the existing default `DATABASE_PATH=database/trendforge.db` is unchanged.
The Render production configuration, endpoints and Streamlit UI are unchanged.

## Windows PowerShell

From the repository root:

```powershell
$env:TRENDFORGE_DATA_DIR = "C:\TrendForgeData"
python -m scripts.initialize_local_storage
python -m scripts.initialize_local_storage --init
python -m scripts.initialize_local_storage --verify "database/trendforge.db"
python -m scripts.initialize_local_storage --backup "database/trendforge.db"
```

To copy an existing verified database to local storage **without replacing the original**:

```powershell
python -m scripts.initialize_local_storage --migrate "database/trendforge.db" "C:\TrendForgeData\database\trendforge.db"
```

Review integrity, record counts and backup before setting `DATABASE_PATH=C:\TrendForgeData\database\trendforge.db` for local PC processes. Do not switch database paths for Render. If the destination already exists, the migration refuses to overwrite it.

Backups use SQLite's online backup API (WAL-aware) and are integrity-checked before publication. No current source database is deleted. Backups remain on the same PC unless separately copied to offsite storage. Run the migration during a maintenance window with the engine stopped and verify data counts before switching writers. Never copy live SQLite database files using a raw filesystem copy.

This batch does not implement PC-to-Render sync, cloud event durability, scheduled jobs, or paper-trading safety. Those require later R70 phases.
