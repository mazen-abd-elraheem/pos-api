"""
Tables Router — /api/tables
Mirrors PHP TableController.php
"""

from datetime import datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


async def _bump_version():
    """Auto-increment change_version after any write."""
    try:
        await execute(
            "UPDATE app_config SET config_value = CAST(config_value AS UNSIGNED) + 1 "
            "WHERE config_key = 'change_version'"
        )
    except Exception:
        pass


@router.get("")
async def index(user_data: dict = Depends(get_current_user)):
    """GET /api/tables — list all tables."""
    tables = await fetch_all(
        "SELECT id, number, capacity, status, current_order_id "
        "FROM tables ORDER BY number ASC"
    )
    return {"tables": tables}


@router.get("/status")
async def tables_with_status(user_data: dict = Depends(get_current_user)):
    """GET /api/tables/status — tables with computed pending/sent/total from order items."""
    tables = await fetch_all(
        "SELECT id, number, capacity, status, current_order_id "
        "FROM tables ORDER BY number ASC"
    )

    # Get all order items grouped by table
    items = await fetch_all(
        "SELECT table_id, status AS item_status, "
        "COALESCE(price, 0) * COALESCE(quantity, 1) AS line_total "
        "FROM table_order_items"
    )

    # Build lookup: table_id -> {pending, sent, total}
    stats: dict[int, dict] = {}
    for item in items:
        tid = item["table_id"]
        if tid not in stats:
            stats[tid] = {"pending_items": 0, "sent_items": 0, "total_amount": 0.0}
        s = stats[tid]
        if item["item_status"] == "pending":
            s["pending_items"] += 1
        elif item["item_status"] in ("sent", "served"):
            s["sent_items"] += 1
        s["total_amount"] += float(item["line_total"] or 0)

    # Merge into tables
    for t in tables:
        tid = t["id"]
        s = stats.get(tid, {})
        t["pending_items"] = s.get("pending_items", 0)
        t["sent_items"] = s.get("sent_items", 0)
        t["total_amount"] = round(s.get("total_amount", 0.0), 2)
        t["order_id"] = t.get("current_order_id")

    return {"tables": tables}


# -- Table Order Items --

@router.get("/{table_id}/items")
async def get_table_items(table_id: int, user_data: dict = Depends(get_current_user)):
    """GET /api/tables/{id}/items — order items for a specific table."""
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
async def add_table_item(table_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/tables/{id}/items — add an item to a table order."""
    product_id = body.get("product_id")
    quantity = body.get("quantity", 1)
    price = body.get("price", 0)
    notes = body.get("notes", "")

    item_id = await execute(
        "INSERT INTO table_order_items (table_id, product_id, quantity, price, notes, status, created_at) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', NOW())",
        [table_id, product_id, quantity, price, notes],
    )

    # Mark table as occupied
    await execute("UPDATE `tables` SET status = 'occupied' WHERE id = %s AND status = 'free'", [table_id])
    await _bump_version()
    return JSONResponse({"success": True, "id": item_id, "message": "Item added"}, status_code=201)


@router.put("/{table_id}/items/send")
async def send_items_to_kitchen(table_id: int, user_data: dict = Depends(get_current_user)):
    """PUT /api/tables/{id}/items/send — mark all pending items as sent."""
    await execute(
        "UPDATE table_order_items SET status = 'sent', sent_at = NOW() "
        "WHERE table_id = %s AND status = 'pending'",
        [table_id],
    )
    await _bump_version()
    return {"message": "Items sent to kitchen"}


@router.delete("/items/{item_id}")
async def remove_table_item(item_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/tables/items/{item_id} — remove a single order item."""
    await execute("DELETE FROM table_order_items WHERE id = %s", [item_id])
    await _bump_version()
    return {"message": "Item removed"}


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
