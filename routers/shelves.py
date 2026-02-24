"""
Shelves Router — /api/shelves
Mirrors PHP ShelfController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, execute
from auth import get_current_user

router = APIRouter()


@router.get("")
async def index(user_data: dict = Depends(get_current_user)):
    """GET /api/shelves — list all shelves."""
    shelves = await fetch_all(
        "SELECT s.*, 0 as product_count FROM shelves s ORDER BY s.shelf_code ASC"
    )
    # Attach empty products array (shelf_products table missing — matches PHP)
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

    return {"message": "Shelf updated"}


@router.delete("/{shelf_id}")
async def destroy(shelf_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/shelves/{id} — delete a shelf."""
    await execute("DELETE FROM shelves WHERE id = %s", [shelf_id])
    return {"message": "Shelf deleted"}
