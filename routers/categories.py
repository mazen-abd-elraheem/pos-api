"""
Categories Router — /api/categories
Mirrors PHP CategoryController.php
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
    """GET /api/categories — list all categories."""
    categories = await fetch_all(
        "SELECT id, name, icon, image FROM categories ORDER BY name ASC"
    )
    return {"categories": categories}


@router.post("")
async def store(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/categories — create a category."""
    name = body.get("name", "")
    if not name:
        return JSONResponse(
            {"error": True, "message": "Category name is required"}, status_code=400
        )

    cid = await execute(
        "INSERT INTO categories (name, icon, image, tenant_id) VALUES (%s, %s, %s, %s)",
        [name, body.get("icon", "CATEGORY"), body.get("image"), body.get("tenant_id")],
    )
    await _bump_version()
    return JSONResponse({"id": cid, "message": "Category created"}, status_code=201)


@router.put("/{category_id}")
async def update(category_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """PUT /api/categories/{id} — update a category."""
    allowed = ["name", "icon", "image"]
    fields, values = [], []
    for f in allowed:
        if f in body:
            fields.append(f"{f} = %s")
            values.append(body[f])

    if not fields:
        return JSONResponse({"error": True, "message": "No fields to update"}, status_code=400)

    values.append(category_id)
    await execute(f"UPDATE categories SET {', '.join(fields)} WHERE id = %s", values)
    await _bump_version()
    return {"message": "Category updated"}


@router.delete("/{name}")
async def destroy(name: str, user_data: dict = Depends(get_current_user)):
    """DELETE /api/categories/{name} — delete by name."""
    await execute("DELETE FROM categories WHERE name = %s", [name])
    await _bump_version()
    return {"message": "Category deleted"}
