"""
Ingredients Router — /api/ingredients
Mirrors PHP IngredientController.php
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
        await _bump_version()
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
        await _bump_version()
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
    await _bump_version()
    return {"success": True, "message": "Ingredient deleted"}


@router.post("/{ingredient_id}/movement")
async def record_movement(ingredient_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/ingredients/{id}/movement — record stock movement."""
    from database import fetch_one as _fetch_one
    ingredient = await _fetch_one("SELECT id, current_stock FROM ingredients WHERE id = %s", [ingredient_id])
    if not ingredient:
        return JSONResponse({"error": True, "message": "Ingredient not found"}, status_code=404)

    quantity = body.get("quantity", 0)
    new_stock = (ingredient["current_stock"] or 0) + quantity

    await execute("UPDATE ingredients SET current_stock = %s WHERE id = %s", [new_stock, ingredient_id])
    await execute(
        "INSERT INTO ingredient_stock_movements (ingredient_id, movement_type, quantity, cost, notes, user, reference_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        [
            ingredient_id,
            body.get("movement_type", "adjustment"),
            quantity,
            body.get("cost", 0),
            body.get("notes", ""),
            body.get("user", ""),
            body.get("reference_id"),
        ],
    )
    await _bump_version()
    return {"success": True, "message": "Movement recorded", "new_stock": new_stock}
