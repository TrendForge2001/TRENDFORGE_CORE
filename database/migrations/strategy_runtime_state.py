"""Persist R72.5 strategy runtime state and execution claims."""


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_runtime_state(
            state_key TEXT PRIMARY KEY,
            state_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_strategy_runtime_state_type_updated
        ON strategy_runtime_state(state_type, updated_at DESC)
        """
    )
