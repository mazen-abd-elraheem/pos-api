"""
Recipes Router — /api/recipes
Mirrors PHP RecipeController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, execute
from auth import get_current_user

router = APIRouter()


@router.get("")
async def index(user_data: dict = Depends(get_current_user)):
    """GET /api/recipes — all products with their recipe items."""
    try:
        items = await fetch_all(
            """SELECT ri.id AS recipe_item_id, ri.product_id, ri.ingredient_id,
                      ri.component_product_id, ri.quantity_needed, ri.recipe_unit,
                      p.title AS product_name, p.image AS product_image,
                      i.name AS ingredient_name, i.unit AS ingredient_unit, i.current_stock,
                      cp.title AS component_product_name, cp.stock AS component_stock,
                      cp.image AS component_image
               FROM recipe_items ri
               JOIN products p ON ri.product_id = p.id
               LEFT JOIN ingredients i ON ri.ingredient_id = i.id
               LEFT JOIN products cp ON ri.component_product_id = cp.id
               ORDER BY p.title ASC, ri.id ASC"""
        )

        recipes: dict[int, dict] = {}
        for item in items:
            pid = item["product_id"]
            if pid not in recipes:
                recipes[pid] = {
                    "product_id": int(pid),
                    "product_name": item["product_name"],
                    "product_image": item["product_image"],
                    "items": [],
                }

            entry = {
                "recipe_item_id": int(item["recipe_item_id"]),
                "quantity_needed": float(item["quantity_needed"]),
                "recipe_unit": item["recipe_unit"],
            }

            if item.get("ingredient_id"):
                entry["type"] = "ingredient"
                entry["ingredient_id"] = int(item["ingredient_id"])
                entry["ingredient_name"] = item["ingredient_name"]
                entry["unit"] = item["recipe_unit"] or item.get("ingredient_unit", "")
                entry["current_stock"] = float(item.get("current_stock") or 0)
            elif item.get("component_product_id"):
                entry["type"] = "product"
                entry["ingredient_id"] = int(item["component_product_id"])
                entry["ingredient_name"] = item["component_product_name"]
                entry["unit"] = "unit"
                entry["current_stock"] = float(item.get("component_stock") or 0)
                entry["image"] = item.get("component_image")

            recipes[pid]["items"].append(entry)

        return {"recipes": list(recipes.values())}
    except Exception as e:
        return {"recipes": [], "_note": f"recipe_items table not available: {str(e)}"}


@router.get("/{product_id}")
async def show(product_id: int, user_data: dict = Depends(get_current_user)):
    """GET /api/recipes/{product_id} — recipe items for one product."""
    try:
        items = await fetch_all(
            """SELECT ri.id AS recipe_item_id, ri.ingredient_id,
                      ri.component_product_id, ri.quantity_needed, ri.recipe_unit,
                      i.name AS ingredient_name, i.unit AS ingredient_unit, i.current_stock,
                      cp.title AS component_product_name, cp.stock AS component_stock,
                      cp.image AS component_image
               FROM recipe_items ri
               LEFT JOIN ingredients i ON ri.ingredient_id = i.id
               LEFT JOIN products cp ON ri.component_product_id = cp.id
               WHERE ri.product_id = %s ORDER BY ri.id ASC""",
            [product_id],
        )

        recipe = []
        for item in items:
            entry = {
                "recipe_item_id": int(item["recipe_item_id"]),
                "quantity_needed": float(item["quantity_needed"]),
                "recipe_unit": item["recipe_unit"],
            }

            if item.get("ingredient_id"):
                entry["type"] = "ingredient"
                entry["ingredient_id"] = int(item["ingredient_id"])
                entry["ingredient_name"] = item["ingredient_name"]
                entry["unit"] = item["recipe_unit"] or item.get("ingredient_unit", "")
                entry["current_stock"] = float(item.get("current_stock") or 0)
            elif item.get("component_product_id"):
                entry["type"] = "product"
                entry["ingredient_id"] = int(item["component_product_id"])
                entry["ingredient_name"] = item["component_product_name"]
                entry["unit"] = "unit"
                entry["current_stock"] = float(item.get("component_stock") or 0)
                entry["image"] = item.get("component_image")

            recipe.append(entry)

        return {"recipe": recipe}
    except Exception as e:
        return {"recipe": [], "_note": str(e)}


@router.post("")
async def store(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/recipes — add a recipe item."""
    product_id = body.get("product_id")
    ingredient_id = body.get("ingredient_id")
    component_product_id = body.get("component_product_id")
    quantity_needed = body.get("quantity_needed")
    recipe_unit = body.get("recipe_unit")

    if not product_id or not quantity_needed:
        return JSONResponse(
            {"error": True, "message": "product_id and quantity_needed are required"},
            status_code=400,
        )

    if not ingredient_id and not component_product_id:
        return JSONResponse(
            {"error": True, "message": "Either ingredient_id or component_product_id is required"},
            status_code=400,
        )

    if component_product_id and str(component_product_id) == str(product_id):
        return JSONResponse(
            {"error": True, "message": "Cannot add a product as an ingredient to itself"},
            status_code=400,
        )

    try:
        rid = await execute(
            "INSERT INTO recipe_items (product_id, ingredient_id, component_product_id, "
            "quantity_needed, recipe_unit) VALUES (%s, %s, %s, %s, %s)",
            [product_id, ingredient_id, component_product_id, quantity_needed, recipe_unit],
        )
        return JSONResponse(
            {"success": True, "message": "Recipe item added", "id": rid}, status_code=201
        )
    except Exception as e:
        return JSONResponse(
            {"error": True, "message": f"Failed to add recipe item: {str(e)}"},
            status_code=500,
        )


@router.delete("/{recipe_id}")
async def destroy(recipe_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/recipes/{id} — delete a recipe item."""
    try:
        await execute("DELETE FROM recipe_items WHERE id = %s", [recipe_id])
        return {"success": True, "message": "Recipe item deleted"}
    except Exception as e:
        return JSONResponse(
            {"error": True, "message": f"Failed to delete recipe item: {str(e)}"},
            status_code=500,
        )
