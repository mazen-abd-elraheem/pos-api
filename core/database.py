"""
POS API — Async SQLAlchemy Database Configuration
Supports both Supabase (PostgreSQL via asyncpg) and MySQL (via aiomysql),
with serverless pooling (pool_pre_ping=True, pool_size=5) for Vercel.
"""

import os
import ssl
import re
import logging
from typing import AsyncGenerator
import urllib.parse
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from core.config import settings

logger = logging.getLogger("database")


def _build_database_config():
    """
    Construct database URL and connect_args.
    Prefers DATABASE_URL (for Supabase / Postgres on Vercel),
    falling back to separate DB_* settings (MySQL).
    """
    raw_url = os.getenv("DATABASE_URL") or settings.DATABASE_URL
    if raw_url and raw_url.strip():
        url_str = raw_url.strip()
        parsed = urlparse(url_str)
        scheme = parsed.scheme.lower()

        # Handle PostgreSQL / Supabase
        if scheme in ("postgres", "postgresql", "postgresql+asyncpg"):
            target_scheme = "postgresql+asyncpg"

            hostname = parsed.hostname or ""
            port = parsed.port or 5432
            username = parsed.username or "postgres"
            password = parsed.password or ""

            # Supabase direct host (db.<ref>.supabase.co) is IPv6-only, causing [Errno 99] on Vercel.
            # Auto-route to Supabase's IPv4 Transaction Pooler (port 6543).
            if hostname.startswith("db.") and hostname.endswith(".supabase.co"):
                ref = hostname.split(".")[1]
                hostname = "aws-0-eu-west-2.pooler.supabase.com"
                port = 6543
                if username == "postgres":
                    username = f"postgres.{ref}"

            _quoted_user = urllib.parse.quote_plus(username)
            _quoted_pwd = f":{urllib.parse.quote_plus(password)}" if password else ""
            netloc = f"{_quoted_user}{_quoted_pwd}@{hostname}:{port}"

            # Parse query params and strip asyncpg-incompatible options like sslmode
            query_params = parse_qs(parsed.query)
            query_params.pop("sslmode", None)

            clean_query = urlencode(query_params, doseq=True)
            clean_url = urlunparse((
                target_scheme,
                netloc,
                parsed.path,
                parsed.params,
                clean_query,
                parsed.fragment,
            ))

            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            # Supabase connection pooler (port 6543) uses pgBouncer in transaction mode.
            # Setting statement_cache_size=0 avoids prepared statement conflicts with pgBouncer.
            connect_args = {
                "ssl": ssl_ctx,
                "statement_cache_size": 0,
            }
            return clean_url, connect_args, "postgresql"

        # Handle MySQL URL
        elif scheme in ("mysql", "mysql+aiomysql"):
            target_scheme = "mysql+aiomysql"
            clean_url = urlunparse((
                target_scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            ))
            ssl_ctx = None
            if settings.DB_SSL or "ssl" in parsed.query:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
            connect_args = {"ssl": ssl_ctx} if ssl_ctx else {}
            return clean_url, connect_args, "mysql"

    # Default fallback: MySQL using individual settings
    _user = urllib.parse.quote_plus(settings.DB_USER)
    _pwd = urllib.parse.quote_plus(settings.DB_PASSWORD) if settings.DB_PASSWORD else ""
    default_url = f"mysql+aiomysql://{_user}:{_pwd}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}?charset=utf8mb4"

    ssl_ctx = None
    if settings.DB_SSL:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    connect_args = {"ssl": ssl_ctx} if ssl_ctx else {}
    return default_url, connect_args, "mysql"


db_url, connect_args, dialect_name = _build_database_config()

# Configure AsyncEngine with serverless disconnect handling
engine = create_async_engine(
    db_url,
    pool_pre_ping=True,  # Gracefully handles disconnects from serverless sleep/restarts
    pool_size=5,          # Small connection pool optimal for Vercel functions
    max_overflow=2,
    pool_recycle=300,     # Recycle connections every 5 minutes
    echo=False,
    connect_args=connect_args,
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
# Cross-Database Raw SQL Helper functions
# ──────────────────────────────────────────────

def _convert_sql(sql: str, params: list | tuple) -> tuple[str, dict]:
    """
    Convert MySQL syntax to PostgreSQL syntax if needed,
    and convert %s placeholders to SQLAlchemy named parameters (:p0, :p1, ...).
    """
    is_pg = getattr(engine.dialect, "name", "") == "postgresql"
    if is_pg:
        # Convert MySQL backticks `table` -> "table"
        sql = re.sub(r'`([^`]+)`', r'"\1"', sql)
        # Avoid Postgres text casting mismatch for increment operations on config_value
        sql = re.sub(
            r'CAST\s*\(\s*config_value\s+AS\s+UNSIGNED\s*\)\s*\+\s*1',
            'CAST(CAST(config_value AS INTEGER) + 1 AS VARCHAR)',
            sql,
            flags=re.IGNORECASE,
        )
        # Convert MySQL AS UNSIGNED -> AS INTEGER
        sql = re.sub(r'\bAS\s+UNSIGNED\b', 'AS INTEGER', sql, flags=re.IGNORECASE)

    if not params:
        return sql, {}

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
    is_pg = getattr(engine.dialect, "name", "") == "postgresql"
    new_sql, bind_params = _convert_sql(sql, params)

    # In PostgreSQL, auto-append RETURNING id for INSERT statements to retrieve generated ID
    if is_pg and new_sql.strip().upper().startswith("INSERT INTO") and "RETURNING" not in new_sql.upper():
        try_sql = new_sql.rstrip().rstrip(";") + " RETURNING id"
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(try_sql), bind_params)
                row = result.first()
                if row and len(row) > 0 and row[0] is not None:
                    return int(row[0])
                return result.rowcount or 0
        except Exception:
            # If RETURNING id is invalid (e.g. table without 'id' column), fallback to standard execution
            pass

    async with engine.begin() as conn:
        result = await conn.execute(text(new_sql), bind_params)
        try:
            if result.lastrowid:
                return result.lastrowid
        except Exception:
            pass
        return result.rowcount or 0


async def execute_transaction(queries: list[tuple[str, list | tuple]]):
    """Execute multiple queries in a single transaction."""
    is_pg = getattr(engine.dialect, "name", "") == "postgresql"
    async with engine.begin() as conn:
        first_id = None
        for sql, params in queries:
            new_sql, bind_params = _convert_sql(sql, params)
            executed = False
            if is_pg and new_sql.strip().upper().startswith("INSERT INTO") and "RETURNING" not in new_sql.upper():
                try_sql = new_sql.rstrip().rstrip(";") + " RETURNING id"
                try:
                    res = await conn.execute(text(try_sql), bind_params)
                    row = res.first()
                    if first_id is None and row and len(row) > 0 and row[0] is not None:
                        first_id = int(row[0])
                    executed = True
                except Exception:
                    executed = False

            if not executed:
                res = await conn.execute(text(new_sql), bind_params)
                try:
                    if first_id is None and res.lastrowid:
                        first_id = res.lastrowid
                except Exception:
                    pass
        return first_id
