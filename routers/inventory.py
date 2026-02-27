"""
Inventory Router — /api/inventory
Stock movements (entries/exits), snapshots, live inventory, and deleted products.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


@router.get("/movements")
async def stock_movements(
    start_date: str = Query(...),
    end_date: str = Query(...),
    user_data: dict = Depends(get_current_user),
):
    """GET /api/inventory/movements — stock entries and exits for a date range."""
    entries = await fetch_all(
        "SELECT name AS product_name, quantity, entry_date AS date "
        "FROM stock_entries WHERE entry_date >= %s AND entry_date <= %s "
        "ORDER BY entry_date DESC",
        [f"{start_date} 00:00:00", f"{end_date} 23:59:59"],
    )
    exits = await fetch_all(
        "SELECT name AS product_name, quantity, exit_date AS date "
        "FROM stock_exits WHERE exit_date >= %s AND exit_date <= %s "
        "ORDER BY exit_date DESC",
        [f"{start_date} 00:00:00", f"{end_date} 23:59:59"],
    )

    # Format dates to strings
    for e in entries:
        if isinstance(e.get("date"), datetime):
            e["date"] = e["date"].strftime("%Y-%m-%d %H:%M")
    for ex in exits:
        if isinstance(ex.get("date"), datetime):
            ex["date"] = ex["date"].strftime("%Y-%m-%d %H:%M")

    return {"entries": entries, "exits": exits}


@router.get("/snapshot")
async def snapshot_by_date(
    date: str = Query(...),
    user_data: dict = Depends(get_current_user),
):
    """GET /api/inventory/snapshot?date=YYYY-MM-DD — snapshot items for a date."""
    snapshot = await fetch_one(
        "SELECT id, date, type, note FROM inventory_snapshots WHERE date = %s LIMIT 1",
        [date],
    )
    if not snapshot:
        return {"snapshot": None, "items": []}

    items = await fetch_all(
        "SELECT product_id, product_name, quantity, price "
        "FROM inventory_snapshot_items WHERE snapshot_id = %s",
        [snapshot["id"]],
    )

    items_data = [
        {
            "product_name": i["product_name"],
            "quantity": i["quantity"] or 0,
            "price": i["price"] or 0,
            "is_deleted": i["product_id"] is None,
        }
        for i in items
    ]

    return {
        "snapshot": {"date": snapshot["date"], "type": snapshot["type"], "note": snapshot.get("note", "")},
        "items": items_data,
    }


@router.get("/live")
async def live_inventory(user_data: dict = Depends(get_current_user)):
    """GET /api/inventory/live — current product stock as snapshot format."""
    products = await fetch_all(
        "SELECT id, title AS product_name, stock AS quantity, price FROM products"
    )

    items = [
        {
            "product_name": p["product_name"],
            "quantity": p["quantity"] or 0,
            "price": p["price"] or 0,
            "is_deleted": False,
        }
        for p in products
    ]

    # Check today's snapshot for deleted products
    today_str = datetime.now().strftime("%Y-%m-%d")
    snapshot = await fetch_one(
        "SELECT id FROM inventory_snapshots WHERE date = %s LIMIT 1", [today_str]
    )
    if snapshot:
        deleted = await fetch_all(
            "SELECT product_name, quantity, price FROM inventory_snapshot_items "
            "WHERE snapshot_id = %s AND product_id IS NULL",
            [snapshot["id"]],
        )
        existing_names = {i["product_name"] for i in items}
        for d in deleted:
            if d["product_name"] not in existing_names:
                items.append({
                    "product_name": d["product_name"],
                    "quantity": 0,
                    "price": d["price"] or 0,
                    "is_deleted": True,
                })

    return {
        "snapshot": {"date": today_str, "type": "live", "note": "Live inventory data"},
        "items": items,
    }


@router.get("/deleted")
async def deleted_products(
    start_date: str = Query(...),
    end_date: str = Query(...),
    user_data: dict = Depends(get_current_user),
):
    """GET /api/inventory/deleted — products deleted within a date range."""
    snapshots = await fetch_all(
        "SELECT id FROM inventory_snapshots WHERE date >= %s AND date <= %s",
        [start_date, end_date],
    )

    if not snapshots:
        return {"deleted": []}

    ids = [s["id"] for s in snapshots]
    placeholders = ",".join(["%s"] * len(ids))

    deleted = await fetch_all(
        f"SELECT product_name, quantity AS last_quantity, price "
        f"FROM inventory_snapshot_items "
        f"WHERE snapshot_id IN ({placeholders}) AND product_id IS NULL",
        ids,
    )

    # Deduplicate by product_name
    seen = set()
    result = []
    for d in deleted:
        if d["product_name"] not in seen:
            result.append(d)
            seen.add(d["product_name"])

    return {"deleted": result}


@router.post("/snapshot")
async def create_snapshot(user_data: dict = Depends(get_current_user)):
    """POST /api/inventory/snapshot — create daily snapshot if not exists."""
    today_str = datetime.now().strftime("%Y-%m-%d")

    existing = await fetch_one(
        "SELECT id FROM inventory_snapshots WHERE date = %s AND type = 'auto_daily' LIMIT 1",
        [today_str],
    )
    if existing:
        return {"message": "Snapshot already exists", "date": today_str}

    snapshot_id = await execute(
        "INSERT INTO inventory_snapshots (date, type, created_at, note) VALUES (%s, 'auto_daily', NOW(), 'Automated daily check')",
        [today_str],
    )

    products = await fetch_all("SELECT id, title, stock, price FROM products")
    for p in products:
        await execute(
            "INSERT INTO inventory_snapshot_items (snapshot_id, product_id, product_name, quantity, cost, price) "
            "VALUES (%s, %s, %s, %s, 0, %s)",
            [snapshot_id, p["id"], p["title"], p["stock"] or 0, p["price"] or 0],
        )

    return {"message": f"Snapshot created with {len(products)} items", "date": today_str}
