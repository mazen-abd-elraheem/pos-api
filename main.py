"""
POS FastAPI — Main Application
Drop-in replacement for the PHP API (index.php).
"""

import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
<<<<<<< HEAD

from config import settings
from database import get_pool, close_pool, fetch_one

# Import routers
from routers import (
=======
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.database import get_pool, close_pool, fetch_one, fetch_all

# Import routers
from controllers import (
>>>>>>> origin/master
    auth,
    startup,
    products,
    sales,
    categories,
    customers,
    ingredients,
    recipes,
    shelves,
    tables,
    permissions,
    settings_router,
<<<<<<< HEAD
=======
    inventory,
    reports,
    users,
    payments,
    config,
    devices,
    bills,
    branches,
    subscriptions,
    sync,
    uploads,
    ai_assistant,
    licenses,
    invoices,
>>>>>>> origin/master
)

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if settings.APP_DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("pos-api")


# ──────────────────────────────────────────────
# Lifespan (startup / shutdown)
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up DB pool on startup, close on shutdown."""
    logger.info(f"Starting POS FastAPI — DB: {settings.DB_HOST}/{settings.DB_NAME}")
    await get_pool()
    logger.info("DB pool ready")
<<<<<<< HEAD
=======
    try:
        from services.inventory_service import check_and_create_daily_snapshot
        await check_and_create_daily_snapshot()
    except Exception as e:
        logger.warning(f"Startup daily snapshot check: {e}")
>>>>>>> origin/master
    yield
    await close_pool()
    logger.info("Shutdown complete")


# ──────────────────────────────────────────────
# App
# ──────────────────────────────────────────────

app = FastAPI(
    title="POS API",
    version="2.0.0",
    description="POS REST API — FastAPI Edition",
    lifespan=lifespan,
)

<<<<<<< HEAD
=======
import os
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

>>>>>>> origin/master
# Gzip compression
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS
origins = settings.ALLOWED_ORIGINS.split(",") if settings.ALLOWED_ORIGINS != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=86400,
)


# ──────────────────────────────────────────────
# Request timing middleware
# ──────────────────────────────────────────────

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Request-Time"] = f"{elapsed}ms"
    return response


<<<<<<< HEAD
=======
# Global exception handler — surface actual errors instead of bare 500
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": True, "message": str(exc), "path": str(request.url.path)},
    )


>>>>>>> origin/master
# ──────────────────────────────────────────────
# Mount routers
# ──────────────────────────────────────────────

app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(startup.router, prefix="/api", tags=["Startup"])
app.include_router(products.router, prefix="/api/products", tags=["Products"])
app.include_router(sales.router, prefix="/api/sales", tags=["Sales"])
app.include_router(categories.router, prefix="/api/categories", tags=["Categories"])
app.include_router(customers.router, prefix="/api/customers", tags=["Customers"])
app.include_router(ingredients.router, prefix="/api/ingredients", tags=["Ingredients"])
app.include_router(recipes.router, prefix="/api/recipes", tags=["Recipes"])
app.include_router(shelves.router, prefix="/api/shelves", tags=["Shelves"])
app.include_router(tables.router, prefix="/api/tables", tags=["Tables"])
app.include_router(permissions.router, prefix="/api/permissions", tags=["Permissions"])
<<<<<<< HEAD
app.include_router(settings_router.router, prefix="/api/settings", tags=["Settings"])
=======
app.include_router(inventory.router, prefix="/api/inventory", tags=["Inventory"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["Settings"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(payments.router, prefix="/api/payments", tags=["Payments"])
app.include_router(config.router, prefix="/api/config", tags=["Config"])
app.include_router(devices.router, prefix="/api/devices", tags=["Devices"])
app.include_router(ai_assistant.router, prefix="/api/ai", tags=["AI Assistant"])
app.include_router(bills.router, prefix="/api/bills", tags=["Bills"])
app.include_router(branches.router, prefix="/api/branches", tags=["Branches"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["Subscriptions"])
app.include_router(sync.router, prefix="/api/sync", tags=["Sync"])
app.include_router(uploads.router, prefix="/api/upload", tags=["Upload"])
app.include_router(licenses.router, prefix="/api/licenses", tags=["Licenses"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["Invoices"])
>>>>>>> origin/master


# ──────────────────────────────────────────────
# Health check + API info (matches PHP index.php)
# ──────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Health check with DB connectivity test."""
    health = {
        "status": "ok",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "fastapi",
    }
    try:
<<<<<<< HEAD
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
=======
        from sqlalchemy import text
        engine = await get_pool()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
>>>>>>> origin/master

        health["database"] = "connected"

        core_tables = [
            "users", "products", "sales", "categories", "customers",
            "ingredients", "shelves", "tables", "permissions", "roles",
        ]
        table_counts = {}
        for table in core_tables:
            try:
                row = await fetch_one(f"SELECT COUNT(*) as cnt FROM `{table}`")
                table_counts[table] = row["cnt"] if row else 0
            except Exception:
                table_counts[table] = "missing"
        health["tables"] = table_counts
    except Exception as e:
        health["database"] = f"error: {str(e)}"

    return health


<<<<<<< HEAD
=======
@app.get("/api/health/schema")
async def schema_check():
    """Show columns for key tables to debug schema mismatches."""
    tables = ["stock_exits", "stock_entries", "sales", "reports", "shelves", "products", "recipe_items", "ingredients"]
    result = {}
    for t in tables:
        try:
            rows = await fetch_all(f"DESCRIBE `{t}`")
            result[t] = [{"field": r["Field"], "type": r["Type"]} for r in rows] if rows else "no rows"
        except Exception as e:
            result[t] = str(e)
    return result


>>>>>>> origin/master
@app.get("/")
@app.get("/api")
async def api_info():
    """API root information."""
    return {
        "name": "POS API",
        "version": "2.0.0",
        "status": "running",
        "engine": "fastapi",
    }
