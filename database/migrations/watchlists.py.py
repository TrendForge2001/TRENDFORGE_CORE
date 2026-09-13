"""Deprecated compatibility wrapper. Canonical migration is watchlists.py."""
from database.migrations.watchlists import migrate
__all__=["migrate"]
