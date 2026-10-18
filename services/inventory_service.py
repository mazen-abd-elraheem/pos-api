"""
pos-api-fastapi/services/inventory_service.py — Inventory & Snapshot Service
Ported from services/inventory_service.py.
Handles automated daily stock snapshots, snapshot querying, and live stock tracking.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from core.database import fetch_all, fetch_one, execute

logger = logging.getLogger("inventory_service")


async def check_and_create_daily_snapshot() -> Optional[int]:
    """Create automated daily snapshot if one doesn't exist for today."""
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        existing = await fetch_one(
            "SELECT id FROM inventory_snapshots WHERE date = %s AND type = 'auto_daily' LIMIT 1",
            [today_str],
        )
        if existing:
            logger.info(f"Daily snapshot for {today_str} already exists (id={existing['id']}).")
            return existing["id"]

        logger.info(f"Creating automated daily snapshot for {today_str}...")
        snapshot_id = await execute(
            "INSERT INTO inventory_snapshots (date, type, note, created_at) "
            "VALUES (%s, 'auto_daily', 'Automated daily inventory check.', %s)",
            [today_str, datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        )

        products = await fetch_all(
            "SELECT id, title, stock, price FROM products WHERE is_active = 1"
        )
        if not products:
            products = await fetch_all("SELECT id, title, stock, price FROM products")

        for p in products:
            try:
                await execute(
                    "INSERT INTO inventory_snapshot_items (snapshot_id, product_id, product_name, quantity, cost, price) "
                    "VALUES (%s, %s, %s, %s, 0, %s)",
                    [
                        snapshot_id,
                        p["id"],
                        p.get("title", ""),
                        p.get("stock") or 0,
                        p.get("price") or 0.0,
                    ],
                )
            except Exception as e:
                logger.warning(f"Could not add snapshot item for product {p.get('id')}: {e}")

        logger.info(f"Snapshot #{snapshot_id} created with {len(products)} products.")
        return snapshot_id
    except Exception as e:
        logger.error(f"Error creating automated daily snapshot: {e}")
        return None


async def get_snapshot_by_date(date_str: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Retrieve snapshot info and item details for a specific date."""
    snapshot = await fetch_one(
        "SELECT id, date, type, note, created_at FROM inventory_snapshots WHERE date = %s ORDER BY id DESC LIMIT 1",
        [date_str],
    )
    if not snapshot:
        return None, []

    items = await fetch_all(
        "SELECT product_id, product_name, quantity, cost, price "
        "FROM inventory_snapshot_items WHERE snapshot_id = %s ORDER BY product_name ASC",
        [snapshot["id"]],
    )

    items_data = [
        {
            "product_id": i.get("product_id"),
            "product_name": i.get("product_name"),
            "quantity": i.get("quantity") or 0,
            "cost": float(i.get("cost") or 0.0),
            "price": float(i.get("price") or 0.0),
            "is_deleted": i.get("product_id") is None,
        }
        for i in items
    ]

    return snapshot, items_data


async def get_available_snapshot_dates() -> List[str]:
    """Returns list of distinct dates that have snapshots recorded."""
    rows = await fetch_all(
        "SELECT DISTINCT date FROM inventory_snapshots ORDER BY date DESC"
    )
    return [str(r["date"]) for r in rows if r.get("date")]


async def get_live_inventory_data() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Retrieve current live inventory items in snapshot format."""
    products = await fetch_all(
        "SELECT id, title, stock, price FROM products ORDER BY title ASC"
    )

    items_data = [
        {
            "product_id": p["id"],
            "product_name": p.get("title", ""),
            "quantity": p.get("stock") or 0,
            "price": float(p.get("price") or 0.0),
            "is_deleted": False,
        }
        for p in products
    ]

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snapshot_meta = {
        "date": now_str[:10],
        "type": "live",
        "note": "Real-time stock status.",
        "created_at": now_str,
        "total_items": len(items_data),
    }

    return snapshot_meta, items_data
