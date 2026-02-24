"""
Ingredients Router — /api/ingredients
Mirrors PHP IngredientController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, execute
from auth import get_current_user

router = APIRouter()


@router.get("")
async def index(user_data: dict = Depends(get_current_user)):
    """GET /api/ingredients — list all ingredients."""
    ingredients = await fetch_all(
        "SELECT id, name, current_stock, unit, cost_per_unit, supplier "
        "FROM ingredients ORDER BY name ASC"
    )
    return {"ingredients": ingredients}


@router.post("")
async def store(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/ingredients — create an ingredient."""
    name = body.get("name", "")
    if not name:
        return JSONResponse(
            {"error": True, "message": "Ingredient name is required"}, status_code=400
        )

    try:
        iid = await execute(
            "INSERT INTO ingredients (name, current_stock, unit, min_stock_level, "
            "cost_per_unit, supplier, notes, image, tenant_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                name,
                body.get("current_stock", 0),
                body.get("unit", "pcs"),
                body.get("min_stock_level", 0),
                body.get("cost_per_unit", 0),
                body.get("supplier", ""),
                body.get("notes", ""),
                body.get("image", "ingredient.png"),
                user_data.get("tenant_id"),
            ],
        )
        return JSONResponse(
            {"success": True, "id": iid, "message": "Ingredient created"}, status_code=201
        )
    except Exception as e:
        if "Duplicate" in str(e) or "1062" in str(e):
            return JSONResponse(
                {"error": True, "message": f"An ingredient with the name '{name}' already exists"},
                status_code=409,
            )
        return JSONResponse(
            {"error": True, "message": f"Failed to create ingredient: {str(e)}"},
            status_code=500,
        )


@router.put("/{ingredient_id}")
async def update(ingredient_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """PUT /api/ingredients/{id} — update an ingredient."""
    allowed = ["name", "current_stock", "unit", "min_stock_level", "cost_per_unit", "supplier", "notes", "image"]
    fields, values = [], []
    for f in allowed:
        if f in body:
            fields.append(f"{f} = %s")
            values.append(body[f])

    if not fields:
        return JSONResponse({"error": True, "message": "No fields to update"}, status_code=400)

    try:
        values.append(ingredient_id)
        await execute(f"UPDATE ingredients SET {', '.join(fields)} WHERE id = %s", values)
        return {"success": True, "message": "Ingredient updated"}
    except Exception as e:
        if "Duplicate" in str(e) or "1062" in str(e):
            return JSONResponse(
                {"error": True, "message": "An ingredient with that name already exists"},
                status_code=409,
            )
        return JSONResponse(
            {"error": True, "message": f"Failed to update ingredient: {str(e)}"},
            status_code=500,
        )


@router.delete("/{ingredient_id}")
async def destroy(ingredient_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/ingredients/{id} — delete an ingredient."""
    await execute("DELETE FROM ingredients WHERE id = %s", [ingredient_id])
    return {"success": True, "message": "Ingredient deleted"}
