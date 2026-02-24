"""
Categories Router — /api/categories
Mirrors PHP CategoryController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, execute
from auth import get_current_user

router = APIRouter()


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
    return JSONResponse({"id": cid, "message": "Category created"}, status_code=201)


@router.delete("/{name}")
async def destroy(name: str, user_data: dict = Depends(get_current_user)):
    """DELETE /api/categories/{name} — delete by name."""
    await execute("DELETE FROM categories WHERE name = %s", [name])
    return {"message": "Category deleted"}
