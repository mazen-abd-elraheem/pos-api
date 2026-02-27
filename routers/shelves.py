"""
Shelves Router — /api/shelves
Mirrors PHP ShelfController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, execute
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
    """GET /api/shelves — list all shelves."""
    shelves = await fetch_all(
        "SELECT s.*, 0 as product_count FROM shelves s ORDER BY s.shelf_code ASC"
    )
    for shelf in shelves:
        shelf["products"] = []
    return {"shelves": shelves}


@router.post("")
async def store(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/shelves — create a shelf."""
    shelf_code = body.get("shelf_code") or body.get("name", "")
    if not shelf_code:
        return JSONResponse(
            {"error": True, "message": "Shelf code/name is required"}, status_code=400
        )

    try:
        sid = await execute(
            "INSERT INTO shelves (shelf_code, description, max_capacity, "
            "current_quantity, product_id, tenant_id) VALUES (%s, %s, %s, %s, %s, %s)",
            [
                shelf_code,
                body.get("description") or body.get("location", ""),
                body.get("max_capacity") or body.get("capacity", 0),
                body.get("current_quantity", 0),
                body.get("product_id"),
                user_data.get("tenant_id"),
            ],
        )
        await _bump_version()
        return JSONResponse(
            {"success": True, "id": sid, "message": "Shelf created"}, status_code=201
        )
    except Exception as e:
        if "Duplicate" in str(e) or "1062" in str(e):
            return JSONResponse(
                {"error": True, "message": f"A shelf with code '{shelf_code}' already exists"},
                status_code=409,
            )
        return JSONResponse(
            {"error": True, "message": f"Failed to create shelf: {str(e)}"}, status_code=500
        )


@router.put("/{shelf_id}")
async def update(shelf_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """PUT /api/shelves/{id} — update a shelf."""
    allowed = ["shelf_code", "description", "max_capacity", "current_quantity", "product_id"]
    fields, values = [], []
    for f in allowed:
        if f in body:
            fields.append(f"{f} = %s")
            values.append(body[f])

    if fields:
        values.append(shelf_id)
        await execute(f"UPDATE shelves SET {', '.join(fields)} WHERE id = %s", values)
        await _bump_version()

    return {"message": "Shelf updated"}


@router.delete("/{shelf_id}")
async def destroy(shelf_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/shelves/{id} — delete a shelf."""
    await execute("DELETE FROM shelves WHERE id = %s", [shelf_id])
    await _bump_version()
    return {"message": "Shelf deleted"}


@router.post("/{shelf_id}/refill")
async def refill(shelf_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/shelves/{id}/refill — move stock from product → shelf."""
    from database import fetch_one as _fetch_one, execute_transaction

    refill_qty = int(body.get("quantity", 0))
    if refill_qty <= 0:
        return JSONResponse({"error": True, "message": "Quantity must be > 0"}, status_code=400)

    shelf = await _fetch_one("SELECT * FROM shelves WHERE id = %s", [shelf_id])
    if not shelf:
        return JSONResponse({"error": True, "message": "Shelf not found"}, status_code=404)

    if not shelf.get("product_id"):
        return JSONResponse({"error": True, "message": "No product assigned to shelf"}, status_code=400)

    product = await _fetch_one("SELECT id, stock, title FROM products WHERE id = %s", [shelf["product_id"]])
    if not product:
        return JSONResponse({"error": True, "message": "Product not found"}, status_code=404)

    current_qty = shelf.get("current_quantity", 0) or 0
    max_cap = shelf.get("max_capacity", 0) or 0

    if current_qty + refill_qty > max_cap:
        return JSONResponse(
            {"error": True, "message": f"Refill exceeds max capacity ({max_cap})"}, status_code=400
        )

    if (product["stock"] or 0) < refill_qty:
        return JSONResponse(
            {"error": True, "message": f"Not enough stock (Available: {product['stock']})"}, status_code=400
        )

    # Atomic update: product stock -= qty, shelf qty += qty
    await execute_transaction([
        ("UPDATE products SET stock = stock - %s WHERE id = %s", [refill_qty, product["id"]]),
        ("UPDATE shelves SET current_quantity = current_quantity + %s WHERE id = %s", [refill_qty, shelf_id]),
    ])
    await _bump_version()
    return {"success": True, "message": "Refill successful!"}
