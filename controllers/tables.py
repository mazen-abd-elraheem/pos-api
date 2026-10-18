"""
Tables Router — /api/tables
Mirrors PHP TableController.php
Optimized: single-query JOINs, transaction batching, DB index
"""

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from core.database import fetch_all, fetch_one, execute, execute_transaction
from auth.security import get_current_user, get_optional_user

router = APIRouter()

# ── Ensure index exists (idempotent, runs once at import) ─────────────────
_idx_ensured = False

async def _ensure_indexes():
    """Create indexes and columns if missing — called lazily on first query."""
    global _idx_ensured
    if _idx_ensured:
        return
    try:
        col_done = await fetch_one(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'table_order_items' AND COLUMN_NAME = 'kitchen_done'"
        )
        if not col_done:
            await execute("ALTER TABLE table_order_items ADD COLUMN kitchen_done INT DEFAULT 0")

        col_sent = await fetch_one(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'table_order_items' AND COLUMN_NAME = 'sent_to_kitchen'"
        )
        if not col_sent:
            await execute("ALTER TABLE table_order_items ADD COLUMN sent_to_kitchen INT DEFAULT 0")

        await execute(
            "CREATE INDEX IF NOT EXISTS idx_toi_table_id "
            "ON table_order_items (table_id)"
        )
        await execute(
            "CREATE INDEX IF NOT EXISTS idx_toi_sent "
            "ON table_order_items (table_id, sent_to_kitchen)"
        )
    except Exception:
        pass  # index may already exist or DB doesn't support IF NOT EXISTS
    _idx_ensured = True


async def _bump_version():
    """Auto-increment change_version after any write."""
    try:
        await execute(
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 "
            "WHERE config_key = 'change_version'"
        )
    except Exception:
        pass


# ── Tables listing ────────────────────────────────────────────────────────

@router.get("")
async def index(user_data: Optional[dict] = Depends(get_optional_user)):
    """GET /api/tables — list all tables."""
    tables = await fetch_all(
        "SELECT id, number, capacity, status, current_order_id "
        "FROM tables ORDER BY number ASC"
    )
    return {"tables": tables}


@router.get("/status")
async def tables_with_status(user_data: Optional[dict] = Depends(get_optional_user)):
    """GET /api/tables/status — tables with computed pending/sent/total.

    Optimized: single query with LEFT JOIN + GROUP BY replaces
    2 queries + Python merge loop.

    Before: O(T + I) time, 2 DB round-trips
    After:  O(T) time, 1 DB round-trip (aggregation done in SQL)
    """
    await _ensure_indexes()

    tables = await fetch_all(
        "SELECT t.id, t.number, t.capacity, t.status, t.current_order_id, "
        "  COALESCE(SUM(CASE WHEN toi.sent_to_kitchen = 0 THEN 1 ELSE 0 END), 0) AS pending_items, "
        "  COALESCE(SUM(CASE WHEN toi.sent_to_kitchen = 1 THEN 1 ELSE 0 END), 0) AS sent_items, "
        "  COALESCE(SUM(CASE WHEN toi.sent_to_kitchen = 0 THEN 1 ELSE 0 END) "
        "         + SUM(CASE WHEN toi.sent_to_kitchen = 1 THEN 1 ELSE 0 END), 0) AS total_items, "
        "  ROUND(COALESCE(SUM(toi.price * toi.quantity), 0), 2) AS total_amount "
        "FROM `tables` t "
        "LEFT JOIN table_order_items toi ON toi.table_id = t.id "
        "GROUP BY t.id, t.number, t.capacity, t.status, t.current_order_id "
        "ORDER BY t.number ASC"
    )

    for t in tables:
        t["order_id"] = t.get("current_order_id")

    return {"tables": tables}


# -- Table Order Items --

@router.get("/{table_id}/items")
@router.get("/{table_id}/orders")
async def get_table_items(table_id: int, user_data: Optional[dict] = Depends(get_optional_user)):
    """GET /api/tables/{id}/items — order items for a specific table.

    O(I_t) where I_t = items for this table. Index on table_id makes this fast.
    """
    items = await fetch_all(
        "SELECT toi.*, p.title AS product_name, p.image AS product_image "
        "FROM table_order_items toi "
        "LEFT JOIN products p ON toi.product_id = p.id "
        "WHERE toi.table_id = %s ORDER BY toi.id ASC",
        [table_id],
    )
    for item in items:
        for k in ("created_at", "sent_at"):
            if isinstance(item.get(k), datetime):
                item[k] = item[k].isoformat()
    return {"items": items}


@router.post("/{table_id}/items")
@router.post("/{table_id}/orders")
async def add_table_item(table_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/tables/{id}/items — add an item to a table order.

    Optimized: Atomic merge. Tries UPDATE first, falls back to INSERT transaction.
    """
    product_id = body.get("product_id")
    product_name = body.get("product_name", "")
    quantity = body.get("quantity", 1)
    price = body.get("price", 0)
    notes = body.get("notes", "")

    # 1. Try atomic merge first (increment quantity of existing pending item)
    updated = await execute(
        "UPDATE table_order_items SET quantity = quantity + %s "
        "WHERE table_id = %s AND product_id = %s AND sent_to_kitchen = 0",
        [quantity, table_id, product_id]
    )

    if updated > 0:
        await execute(
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 "
            "WHERE config_key = 'change_version'"
        )
        return JSONResponse({"success": True, "message": "Item quantity merged"}, status_code=200)

    # 2. Insert new item if not merged
    item_id = await execute_transaction([
        (
            "INSERT INTO table_order_items "
            "(table_id, product_id, product_name, quantity, price, notes, sent_to_kitchen, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 0, NOW())",
            [table_id, product_id, product_name, quantity, price, notes],
        ),
        (
            "UPDATE `tables` SET status = 'occupied' WHERE id = %s AND status = 'free'",
            [table_id],
        ),
        (
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 "
            "WHERE config_key = 'change_version'",
            [],
        ),
    ])

    return JSONResponse({"success": True, "id": item_id, "message": "Item added"}, status_code=201)


@router.get("/kitchen/orders")
@router.get("/kitchen/tickets")
@router.get("/kitchen")
async def get_kitchen_tickets(user_data: Optional[dict] = Depends(get_optional_user)):
    """GET /api/tables/kitchen/orders — returns all active kitchen items grouped by table."""
    await _ensure_indexes()
    items = await fetch_all(
        "SELECT toi.*, p.title AS product_name, p.image AS product_image, t.number AS table_number "
        "FROM table_order_items toi "
        "JOIN `tables` t ON toi.table_id = t.id "
        "LEFT JOIN products p ON toi.product_id = p.id "
        "WHERE COALESCE(toi.kitchen_done, 0) = 0 "
        "  AND (toi.sent_to_kitchen = 1 OR t.status = 'occupied') "
        "ORDER BY toi.created_at ASC, toi.id ASC"
    )
    for item in items:
        for k in ("created_at", "sent_at"):
            if isinstance(item.get(k), datetime):
                item[k] = item[k].isoformat()
    return {"items": items}


@router.put("/{table_id}/items/send")
@router.post("/{table_id}/send-to-kitchen")
async def send_items_to_kitchen(table_id: int, user_data: Optional[dict] = Depends(get_optional_user)):
    """PUT /api/tables/{id}/items/send — mark all pending items as sent.

    Optimized: 2 queries → 1 transaction.
    """
    await _ensure_indexes()
    await execute_transaction([
        (
            "UPDATE table_order_items SET sent_to_kitchen = 1, sent_at = NOW() "
            "WHERE table_id = %s AND sent_to_kitchen = 0",
            [table_id],
        ),
        (
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 "
            "WHERE config_key = 'change_version'",
            [],
        ),
    ])
    return {"message": "Items sent to kitchen"}


# ── Kitchen Done ──────────────────────────────────────────────────────────

@router.put("/{table_id}/orders/{item_id}/done")
@router.put("/{table_id}/items/{item_id}/done")
@router.post("/{table_id}/orders/{item_id}/done")
@router.post("/{table_id}/items/{item_id}/done")
@router.put("/orders/{item_id}/done")
@router.post("/orders/{item_id}/done")
async def mark_item_done(item_id: int, table_id: Optional[int] = None, user_data: Optional[dict] = Depends(get_optional_user)):
    """Mark a kitchen item as done."""
    await _ensure_indexes()
    sql = "UPDATE table_order_items SET kitchen_done = 1 WHERE id = %s"
    params = [item_id]
    if table_id is not None:
        sql += " AND table_id = %s"
        params.append(table_id)

    await execute_transaction([
        (sql, params),
        (
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 WHERE config_key = 'change_version'",
            [],
        ),
    ])
    return {"message": "Item marked as done"}


@router.post("/{table_id}/kitchen-done")
@router.put("/{table_id}/kitchen-done")
@router.post("/{table_id}/done")
@router.put("/{table_id}/done")
async def mark_table_kitchen_done(table_id: int, user_data: Optional[dict] = Depends(get_optional_user)):
    """Mark all kitchen items for this table as done."""
    await _ensure_indexes()
    await execute_transaction([
        (
            "UPDATE table_order_items SET kitchen_done = 1 WHERE table_id = %s",
            [table_id],
        ),
        (
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 WHERE config_key = 'change_version'",
            [],
        ),
    ])
    return {"message": "All items for table marked as done"}


@router.delete("/items/{item_id}")
@router.delete("/{table_id}/items/{item_id}")
@router.delete("/{table_id}/orders/{item_id}")
async def remove_table_item(item_id: int, table_id: Optional[int] = None, user_data: Optional[dict] = Depends(get_optional_user)):
    """DELETE /api/tables/items/{item_id} — remove a single order item."""
    await execute_transaction([
        ("DELETE FROM table_order_items WHERE id = %s", [item_id]),
        (
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 "
            "WHERE config_key = 'change_version'",
            [],
        ),
    ])
    return {"message": "Item removed"}


@router.post("/{table_id}/free")
@router.put("/{table_id}/free")
async def free_table(table_id: int, user_data: Optional[dict] = Depends(get_optional_user)):
    """POST /api/tables/{id}/free — clear table and mark as free."""
    await execute_transaction([
        ("DELETE FROM table_order_items WHERE table_id = %s", [table_id]),
        ("UPDATE `tables` SET status = 'free', current_order_id = 0 WHERE id = %s", [table_id]),
        (
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 "
            "WHERE config_key = 'change_version'",
            [],
        ),
    ])
    return {"message": "Table freed"}


# -- Table CRUD --

@router.put("/{table_id}")
async def update(table_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """PUT /api/tables/{id} — update a table."""
    allowed = ["number", "capacity", "status", "current_order_id"]
    fields, values = [], []
    for f in allowed:
        if f in body:
            fields.append(f"{f} = %s")
            values.append(body[f])

    if not fields:
        return JSONResponse(
            {"error": True, "message": "No fields to update"}, status_code=400
        )

    values.append(table_id)
    await execute(f"UPDATE `tables` SET {', '.join(fields)} WHERE id = %s", values)
    return {"message": "Table updated"}


@router.post("")
async def create_table(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/tables — create a new table."""
    number = body.get("number")
    capacity = body.get("capacity", 4)

    existing = await fetch_one("SELECT id FROM `tables` WHERE number = %s", [number])
    if existing:
        return JSONResponse(
            {"error": True, "message": "Table with this number already exists"},
            status_code=409,
        )

    tid = await execute(
        "INSERT INTO `tables` (number, capacity, status, current_order_id) VALUES (%s, %s, 'free', 0)",
        [number, capacity],
    )
    return JSONResponse({"id": tid, "message": "Table created"}, status_code=201)


@router.delete("/{table_id}")
async def delete_table(table_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/tables/{id} — delete a table."""
    await execute("DELETE FROM `tables` WHERE id = %s", [table_id])
    return {"message": "Table deleted"}
