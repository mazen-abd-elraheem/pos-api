"""
services/event_bus.py — Decoupled cross-component communication

Replaces tight coupling like:
    clear_products_cache()
    clear_ingredients_cache()
    clear_shelves_cache()
    bump_change_version()

With:
    bus.emit("sale_completed", sale_id=sale_id)

Handlers are registered once at startup and fire automatically.
Thread-safe via a threading.Lock on the handler registry.

Usage:
    from services.event_bus import bus

    # Subscribe (typically in module init or __init__):
    bus.subscribe("sale_completed", lambda **kw: clear_products_cache())
    bus.subscribe("sale_completed", lambda **kw: clear_shelves_cache())

    # Emit (from any thread):
    bus.emit("sale_completed", sale_id=42, total=150.00)
"""

import logging
import threading
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Singleton in-process event bus. Thread-safe."""

    _instance = None
    _creation_lock = threading.Lock()

    def __new__(cls):
        with cls._creation_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._handlers = defaultdict(list)
                inst._lock = threading.Lock()
                cls._instance = inst
            return cls._instance

    # ── Public API ──

    def subscribe(self, event: str, handler: Callable):
        """Register a handler for an event. Idempotent."""
        with self._lock:
            if handler not in self._handlers[event]:
                self._handlers[event].append(handler)
                logger.debug(f"EventBus: subscribed to '{event}' → {handler.__name__ if hasattr(handler, '__name__') else handler}")

    def emit(self, event: str, **kwargs):
        """Fire all handlers for an event. Errors are logged, never raised."""
        with self._lock:
            handlers = list(self._handlers.get(event, []))

        for handler in handlers:
            try:
                handler(**kwargs)
            except Exception as ex:
                handler_name = getattr(handler, '__name__', str(handler))
                logger.error(f"EventBus: handler '{handler_name}' for '{event}' failed: {ex}")

    def clear(self, event: str = None):
        """Clear handlers. If event is None, clear ALL handlers."""
        with self._lock:
            if event:
                self._handlers.pop(event, None)
            else:
                self._handlers.clear()

    @property
    def events(self):
        """List all registered event names."""
        with self._lock:
            return list(self._handlers.keys())


# ── Module-level singleton ──
bus = EventBus()


# ── Standard events (constants to avoid typos) ──
SALE_COMPLETED = "sale_completed"
PRODUCT_UPDATED = "product_updated"
PRODUCT_DELETED = "product_deleted"
STOCK_CHANGED = "stock_changed"
CACHE_INVALIDATED = "cache_invalidated"
TABLE_UPDATED = "table_updated"
CUSTOMER_UPDATED = "customer_updated"
SETTINGS_CHANGED = "settings_changed"
USER_LOGGED_IN = "user_logged_in"
USER_LOGGED_OUT = "user_logged_out"
