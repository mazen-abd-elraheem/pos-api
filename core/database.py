"""
POS API — Async SQLAlchemy Database Configuration
Provides both raw SQL wrappers (backward compatibility) and ORM sessions.
"""

import ssl
import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
import urllib.parse
from core.config import settings

logger = logging.getLogger("database")

# Build async database URL
_user = urllib.parse.quote_plus(settings.DB_USER)
_pwd = urllib.parse.quote_plus(settings.DB_PASSWORD) if settings.DB_PASSWORD else ""
db_url = f"mysql+aiomysql://{_user}:{_pwd}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}?charset=utf8mb4"

ssl_ctx = None
if settings.DB_SSL:
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

engine = create_async_engine(
    db_url,
    pool_size=10,
    max_overflow=20,
    echo=False,  # Set to True for SQL query logging
    connect_args={"ssl": ssl_ctx} if ssl_ctx else {},
)

async_session_maker = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency for getting SQLAlchemy session."""
    async with async_session_maker() as session:
        yield session

async def get_pool():
    """Dummy pool function to maintain compatibility with main.py startup/shutdown."""
    return engine

async def close_pool():
    """Close the SQLAlchemy engine on shutdown."""
    await engine.dispose()
    logger.info("Database engine closed")

# ──────────────────────────────────────────────
# Legacy Raw SQL Helper functions (using SQLAlchemy text)
# ──────────────────────────────────────────────
# These are kept for backward compatibility with controllers not yet fully migrated to ORM.
# Warning: These wrappers replace raw '%s' with SQLAlchemy bind parameters (':param_1', etc)
# to maintain aiomysql string formatting syntax.

def _convert_sql(sql: str, params: list | tuple) -> tuple[str, dict]:
    """Convert aiomysql %s placeholders to SQLAlchemy named parameters."""
    if not params:
        return sql, {}
    
    # We need to replace %s with :p0, :p1, etc.
    # Note: This is a simplistic approach and assumes no escaped %s in the string.
    bind_params = {}
    parts = sql.split('%s')
    new_sql = parts[0]
    for i, part in enumerate(parts[1:]):
        bind_name = f"p{i}"
        bind_params[bind_name] = params[i]
        new_sql += f":{bind_name}" + part
        
    return new_sql, bind_params

async def fetch_all(sql: str, params: list | tuple = ()) -> list[dict]:
    """Execute query and return all rows as dicts."""
    new_sql, bind_params = _convert_sql(sql, params)
    async with engine.connect() as conn:
        result = await conn.execute(text(new_sql), bind_params)
        return [dict(row) for row in result.mappings().all()]

async def fetch_one(sql: str, params: list | tuple = ()) -> dict | None:
    """Execute query and return first row as dict."""
    new_sql, bind_params = _convert_sql(sql, params)
    async with engine.connect() as conn:
        result = await conn.execute(text(new_sql), bind_params)
        row = result.mappings().first()
        return dict(row) if row else None

async def fetch_column(sql: str, params: list | tuple = ()):
    """Fetch the first column of the first row."""
    new_sql, bind_params = _convert_sql(sql, params)
    async with engine.connect() as conn:
        result = await conn.execute(text(new_sql), bind_params)
        row = result.first()
        return row[0] if row else None

async def execute(sql: str, params: list | tuple = ()) -> int:
    """Execute INSERT/UPDATE/DELETE. Returns last-insert-id for inserts, else affected rows."""
    new_sql, bind_params = _convert_sql(sql, params)
    async with engine.begin() as conn:
        result = await conn.execute(text(new_sql), bind_params)
        return result.lastrowid if result.lastrowid else result.rowcount

async def execute_transaction(queries: list[tuple[str, list | tuple]]):
    """Execute multiple queries in a single transaction."""
    async with engine.begin() as conn:
        first_id = None
        for sql, params in queries:
            new_sql, bind_params = _convert_sql(sql, params)
            result = await conn.execute(text(new_sql), bind_params)
            if first_id is None and result.lastrowid:
                first_id = result.lastrowid
        return first_id
