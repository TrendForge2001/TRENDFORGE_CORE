"""Create stable storage identity and boot evidence for persistence checks."""


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_runtime_state(
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            storage_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            first_boot_at TEXT NOT NULL,
            last_boot_at TEXT NOT NULL,
            boot_count INTEGER NOT NULL DEFAULT 0,
            last_git_commit TEXT,
            last_service_id TEXT
        )
        """
    )
