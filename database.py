"""
POS API — Database Bridge
Re-exports from core.database for backward compatibility with older scripts.
"""

from core.database import (
    engine,
    get_db,
    get_pool,
    close_pool,
    fetch_all,
    fetch_one,
    fetch_column,
    execute,
    execute_transaction,
)

__all__ = [
    "engine",
    "get_db",
    "get_pool",
    "close_pool",
    "fetch_all",
    "fetch_one",
    "fetch_column",
    "execute",
    "execute_transaction",
]
