"""
Tables Router — /api/tables
Mirrors PHP TableController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


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

    # Build lookup: table_id → {pending, sent, total}
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

    # Check for duplicate table number
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
