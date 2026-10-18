"""
services/worker.py â€” Non-blocking DB worker for Flet 0.82+

Provides a centralized async bridge between Flet's UI thread and
synchronous database operations. All heavy MySQL/SQLAlchemy work
runs in a bounded ThreadPoolExecutor so the UI never freezes.

Usage in any page:
    from services.worker import run_db_task, fire_and_forget

    # Option 1: Inside an async function (via page.run_task)
    async def _load():
        products = await run_db_task(get_products)
        self.product_list.controls = [build_card(p) for p in products]
        self.product_list.update()
    page.run_task(_load)

    # Option 2: Fire-and-forget from any event handler
    fire_and_forget(page, _load)

    # Option 3: One-liner for simple DB writes
    fire_and_forget_write(page, update_product, product_id, data,
                          success_msg="Product saved!")
"""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar, Callable, Any, Optional

logger = logging.getLogger(__name__)

T = TypeVar("T")

# â”€â”€ Shared thread pool for ALL background DB work â”€â”€
# Bounded to 8 workers to prevent MySQL connection exhaustion.
# With pool_size=10 + max_overflow=5 = 15 max connections,
# 8 workers ensures we never exceed the pool capacity.
_db_pool = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="pos-db-worker",
)


async def run_db_task(fn: Callable[..., T], *args, **kwargs) -> T:
    """Run a synchronous function in the DB thread pool.

    Safe to call from Flet async callbacks or page.run_task().
    Returns the function's return value.

    Example:
        products = await run_db_task(get_products, force_refresh=True)
        tables = await run_db_task(get_all_tables_with_status)
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_db_pool, lambda: fn(*args, **kwargs))


def fire_and_forget(page, async_coro_fn):
    """Schedule an async coroutine function on the Flet event loop.

    Use when you need to do DB work + UI updates from a synchronous
    event handler (on_click, on_change, etc.).

    Example:
        def on_save_click(e):
            async def _save():
                await run_db_task(update_product, product_id, data)
                _snack(page, "Saved!")
            fire_and_forget(page, _save)
    """
    try:
        page.run_task(async_coro_fn)
    except Exception as ex:
        logger.error(f"fire_and_forget error: {ex}")


def fire_and_forget_write(page, fn, *args, success_msg: str = None,
                          error_msg: str = "Operation failed",
                          on_success=None, on_error=None):
    """One-liner for fire-and-forget DB writes with optional snackbar.

    Example:
        fire_and_forget_write(page, delete_product, product_id,
                              success_msg="Product deleted!")
    """
    import flet as ft

    async def _run():
        try:
            result = await run_db_task(fn, *args)
            if on_success:
                on_success(result)
            if success_msg and page:
                try:
                    page.show_dialog(
                        ft.SnackBar(content=ft.Text(success_msg),
                                    bgcolor=ft.Colors.GREEN)
                    )
                except Exception:
                    pass
        except Exception as ex:
            logger.error(f"fire_and_forget_write error: {ex}")
            if on_error:
                on_error(ex)
            if page:
                try:
                    page.show_dialog(
                        ft.SnackBar(content=ft.Text(f"{error_msg}: {ex}"),
                                    bgcolor=ft.Colors.RED)
                    )
                except Exception:
                    pass

    fire_and_forget(page, _run)


def run_in_bg_thread(fn, *args, callback=None, error_callback=None):
    """Submit work to the thread pool without async (legacy compatibility).

    Use this as a drop-in replacement for:
        threading.Thread(target=fn, args=args, daemon=True).start()

    But with bounded concurrency and error propagation.
    """
    def _wrapper():
        try:
            result = fn(*args)
            if callback:
                callback(result)
        except Exception as e:
            logger.error(f"Background task error: {e}")
            if error_callback:
                error_callback(e)

    _db_pool.submit(_wrapper)


def shutdown_pool():
    """Graceful shutdown. Call on app exit."""
    _db_pool.shutdown(wait=False)
