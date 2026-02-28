"""
Bills Router — /api/bills
Open bill management: CRUD operations, add items, close/convert to sale.
"""

import json
from datetime import datetime
from fastapi import APIRouter, Depends, Body
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


# ── Bill CRUD ──

@router.get("")
async def get_bills(user: dict = Depends(get_current_user)):
    """GET /api/bills — list all open bills."""
    rows = await fetch_all(
        "SELECT id, customer, table_id FROM bills ORDER BY id DESC"
    )
    # Attach item count for each bill
    for bill in rows:
        items = await fetch_all(
            "SELECT id, items FROM bill_items WHERE bill_id = %s", [bill["id"]]
        )
        products = []
        for item_row in items:
            raw = item_row.get("items")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = []
            if isinstance(raw, list):
                products.extend(raw)
        bill["products"] = products
        bill["total_items"] = len(items)
    return {"bills": rows}


@router.get("/{bill_id}")
async def get_bill(bill_id: int, user: dict = Depends(get_current_user)):
    """GET /api/bills/{id} — get bill info with totals."""
    bill = await fetch_one("SELECT id, customer, table_id FROM bills WHERE id = %s", [bill_id])
    if not bill:
        return JSONResponse({"error": True, "message": "Bill not found"}, status_code=404)

    items = await fetch_all(
        "SELECT id, items, date FROM bill_items WHERE bill_id = %s", [bill_id]
    )

    all_products = []
    for item_row in items:
        raw = item_row.get("items")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        if isinstance(raw, list):
            all_products.extend(raw)
        for k in ("date",):
            if isinstance(item_row.get(k), datetime):
                item_row[k] = item_row[k].isoformat()

    total_amount = sum(
        float(p.get("price", 0)) * int(p.get("quantity", 1)) for p in all_products
    )

    return {
        "bill": bill,
        "items": items,
        "total_amount": total_amount,
        "total_products": len(all_products),
        "total_orders": len(items),
    }


@router.post("")
async def create_bill(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/bills — create a new open bill."""
    customer = body.get("customer", "")
    if not customer:
        return JSONResponse(
            {"error": True, "message": "Customer name is required"}, status_code=400
        )

    bill_id = await execute(
        "INSERT INTO bills (customer, table_id, tenant_id) VALUES (%s, %s, %s)",
        [customer, body.get("table_id"), user.get("tenant_id")],
    )
    return JSONResponse({"id": bill_id, "message": "Bill created"}, status_code=201)


@router.delete("/{bill_id}")
async def delete_bill(bill_id: int, user: dict = Depends(get_current_user)):
    """DELETE /api/bills/{id} — delete a bill and its items."""
    # Delete items first (cascade may handle this, but be explicit)
    await execute("DELETE FROM bill_items WHERE bill_id = %s", [bill_id])
    await execute("DELETE FROM bills WHERE id = %s", [bill_id])
    return {"message": "Bill deleted"}


# ── Bill Items ──

@router.post("/{bill_id}/items")
async def add_items_to_bill(bill_id: int, body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/bills/{id}/items — add items to a bill."""
    items = body.get("items", [])
    if not items:
        return JSONResponse(
            {"error": True, "message": "Items list is required"}, status_code=400
        )

    # Verify bill exists
    bill = await fetch_one("SELECT id FROM bills WHERE id = %s", [bill_id])
    if not bill:
        return JSONResponse({"error": True, "message": "Bill not found"}, status_code=404)

    # Store items as JSON
    items_json = json.dumps(items, ensure_ascii=False) if not isinstance(items, str) else items
    item_id = await execute(
        "INSERT INTO bill_items (items, bill_id, tenant_id) VALUES (%s, %s, %s)",
        [items_json, bill_id, user.get("tenant_id")],
    )
    return JSONResponse({"id": item_id, "message": "Items added to bill"}, status_code=201)


# ── Convert Bill to Sale ──

@router.post("/{bill_id}/convert")
async def convert_bill_to_sale(bill_id: int, user: dict = Depends(get_current_user)):
    """POST /api/bills/{id}/convert — get bill items in sale format for closing."""
    items = await fetch_all(
        "SELECT id, items, date FROM bill_items WHERE bill_id = %s", [bill_id]
    )

    orders = []
    for item_row in items:
        raw = item_row.get("items")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        entry = {
            "id": item_row["id"],
            "items": raw if isinstance(raw, list) else [],
            "bill_id": bill_id,
        }
        if isinstance(item_row.get("date"), datetime):
            entry["date"] = item_row["date"].isoformat()
        else:
            entry["date"] = str(item_row.get("date", ""))
        orders.append(entry)

    return {"orders": orders}
