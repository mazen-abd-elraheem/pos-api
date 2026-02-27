"""
POS API — Async MySQL Database Pool
Drop-in replacement for PHP Database.php using aiomysql.
"""

import ssl
import logging
import time
import aiomysql
from config import settings

logger = logging.getLogger("database")

# Global pool reference
_pool: aiomysql.Pool | None = None


async def get_pool() -> aiomysql.Pool:
    """Get or create the global connection pool."""
    global _pool
    if _pool is None or _pool.closed:
        ssl_ctx = None
        if settings.DB_SSL:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        _pool = await aiomysql.create_pool(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            db=settings.DB_NAME,
            charset="utf8mb4",
            autocommit=True,
            minsize=2,
            maxsize=10,
            ssl=ssl_ctx,
        )
        logger.info(f"DB pool created: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    return _pool


async def close_pool():
    """Close the pool on shutdown."""
    global _pool
    if _pool and not _pool.closed:
        _pool.close()
        await _pool.wait_closed()
        logger.info("DB pool closed")
        _pool = None


# ──────────────────────────────────────────────
# Helper functions (mirror PHP Database class)
# ──────────────────────────────────────────────

async def fetch_all(sql: str, params: list | tuple = ()) -> list[dict]:
    """Execute query and return all rows as dicts."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def fetch_one(sql: str, params: list | tuple = ()) -> dict | None:
    """Execute query and return first row as dict."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()


async def fetch_column(sql: str, params: list | tuple = ()):
    """Fetch the first column of the first row."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
            return row[0] if row else None


async def execute(sql: str, params: list | tuple = ()) -> int:
    """Execute INSERT/UPDATE/DELETE. Returns last-insert-id for inserts, else affected rows."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            await conn.commit()
            return cur.lastrowid if cur.lastrowid else cur.rowcount


async def execute_transaction(queries: list[tuple[str, list | tuple]]):
    """Execute multiple queries in a single transaction.

    Args:
        queries: list of (sql, params) tuples
    Returns:
        lastrowid of the first INSERT in the batch
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.begin()
        first_id = None
        try:
            async with conn.cursor() as cur:
                for sql, params in queries:
                    await cur.execute(sql, params)
                    if first_id is None and cur.lastrowid:
                        first_id = cur.lastrowid
            await conn.commit()
            return first_id
        except Exception:
            await conn.rollback()
            raise
