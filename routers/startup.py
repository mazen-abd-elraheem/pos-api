"""
Startup Router — GET /api/startup
THE MAGIC ENDPOINT: returns ALL data in one call.
Uses asyncio.gather() for concurrent queries (faster than PHP sequential).
Mirrors PHP StartupController.php
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends

from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


async def _get_user_permissions(user_id: int, role: str) -> list[str]:
    """Get all permission names for a user (matches PHP getUserPermissions)."""
    if role == "master_admin":
        try:
            perms = await fetch_all("SELECT name FROM permissions")
            return [p["name"] for p in perms]
        except Exception:
            return ["*"]

    granted: dict[str, bool] = {}

    # Role-based permissions
    try:
        role_obj = await fetch_one("SELECT id FROM roles WHERE name = %s", [role])
        if role_obj:
            role_perms = await fetch_all(
                """SELECT p.name FROM role_permissions rp
                   JOIN permissions p ON rp.permission_id = p.id
                   WHERE rp.role_id = %s""",
                [role_obj["id"]],
            )
            for rp in role_perms:
                granted[rp["name"]] = True
    except Exception:
        pass

    # User-specific overrides
    try:
        user_perms = await fetch_all(
            """SELECT p.name, up.granted FROM user_permissions up
               JOIN permissions p ON up.permission_id = p.id
               WHERE up.user_id = %s""",
            [user_id],
        )
        for up in user_perms:
            if up["granted"]:
                granted[up["name"]] = True
            else:
                granted.pop(up["name"], None)
    except Exception:
        pass

    return list(granted.keys())


async def _get_store_settings(tenant_id) -> dict:
    """Get store settings (matches PHP getStoreSettings)."""
    result = {}

    try:
        configs = await fetch_all("SELECT config_key, config_value FROM app_config")
        for c in configs:
            result[c["config_key"]] = c["config_value"]
    except Exception:
        pass

    try:
        if tenant_id:
            store = await fetch_one(
                "SELECT * FROM store_settings WHERE tenant_id = %s", [tenant_id]
            )
        else:
            store = await fetch_one("SELECT * FROM store_settings LIMIT 1")
        if store:
            result.update(store)
    except Exception:
        pass

    return result


@router.get("/startup")
async def get_all(user_data: dict = Depends(get_current_user)):
    """Returns everything the POS needs after login — all in one call."""
    user_id = user_data["user_id"]

    # Get user + tenant
    user = await fetch_one("SELECT * FROM users WHERE id = %s", [user_id])
    tenant_id = user.get("tenant_id") if user else None

    tf = " AND tenant_id = %s" if tenant_id else ""
    tp = [tenant_id] if tenant_id else []

    # Run ALL queries concurrently with asyncio.gather
    (
        products,
        categories,
        ingredients,
        shelves,
        tables,
        payment_methods,
        customers,
        users,
        discounts,
        open_bills,
        permissions,
        store_settings,
        recipe_items,
    ) = await asyncio.gather(
        # 1. Products
        _safe(fetch_all,
              f"SELECT id, title, price, stock, barcode, category, image, "
              f"cost_price, regular_price, sale_price, margin "
              f"FROM products WHERE 1=1 {tf} ORDER BY title ASC", tp),
        # 2. Categories
        _safe(fetch_all,
              f"SELECT id, name, icon, image FROM categories WHERE 1=1 {tf} ORDER BY name ASC", tp),
        # 3. Ingredients
        _safe(fetch_all,
              f"SELECT id, name, current_stock, unit, cost_per_unit, supplier, "
              f"min_stock_level, notes, image "
              f"FROM ingredients WHERE 1=1 {tf} ORDER BY name ASC", tp),
        # 4. Shelves
        _safe(fetch_all,
              f"SELECT s.*, 0 as product_count FROM shelves s WHERE 1=1"
              + (f" AND s.tenant_id = %s" if tenant_id else "") + " ORDER BY s.id ASC", tp),
        # 5. Tables
        _safe(fetch_all,
              f"SELECT id, number, capacity, status, current_order_id "
              f"FROM tables WHERE 1=1 {tf} ORDER BY number ASC", tp),
        # 6. Payment Methods
        _safe(fetch_all,
              f"SELECT * FROM payment_methods WHERE active = 1"
              + (f" AND tenant_id = %s" if tenant_id else ""), tp),
        # 7. Customers
        _safe(fetch_all,
              f"SELECT id, name, phone, email, loyalty_points, total_purchases, discount_percentage "
              f"FROM customers WHERE 1=1 {tf} ORDER BY name ASC", tp),
        # 8. Users
        _safe(fetch_all,
              f"SELECT id, username, name, role FROM users WHERE 1=1 {tf}", tp),
        # 9. Discounts
        _safe(fetch_all,
              f"SELECT id, name, discount_type, value, start_date, end_date, active, "
              f"applicable_to, product_id, category "
              f"FROM discounts WHERE active = 1"
              + (f" AND tenant_id = %s" if tenant_id else ""), tp),
        # 10. Open Bills
        _safe(fetch_all,
              f"SELECT b.id, b.customer, b.status, b.total, b.table_id, b.payment_method, b.notes "
              f"FROM bills b WHERE b.status IN ('open', 'pending')"
              + (f" AND b.tenant_id = %s" if tenant_id else "")
              + " ORDER BY b.id DESC", tp),
        # 11. Permissions
        _get_user_permissions(user_id, user_data["role"]),
        # 12. Store Settings
        _get_store_settings(tenant_id),
        # 13. Recipe Items
        _safe(fetch_all,
              """SELECT ri.id AS recipe_item_id, ri.product_id, ri.ingredient_id,
                        ri.component_product_id, ri.quantity_needed, ri.recipe_unit,
                        i.name AS ingredient_name, i.unit AS ingredient_unit, i.current_stock,
                        cp.title AS component_product_name, cp.stock AS component_stock
                 FROM recipe_items ri
                 LEFT JOIN ingredients i ON ri.ingredient_id = i.id
                 LEFT JOIN products cp ON ri.component_product_id = cp.id
                 ORDER BY ri.product_id ASC, ri.id ASC"""),
    )

    # Group recipes by product_id (matches PHP logic)
    recipes: dict[int, list] = {}
    for item in (recipe_items or []):
        pid = item["product_id"]
        if pid not in recipes:
            recipes[pid] = []

        entry = {
            "recipe_item_id": int(item["recipe_item_id"]),
            "product_id": int(pid),
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

        recipes[pid].append(entry)

    return {
        "user": {
            "id": int(user["id"]),
            "name": user.get("name") or user.get("username") or "Unknown",
            "username": user["username"],
            "role": user["role"],
        },
        "permissions": permissions,
        "products": products or [],
        "categories": categories or [],
        "ingredients": ingredients or [],
        "recipes": recipes,
        "shelves": shelves or [],
        "tables": tables or [],
        "payment_methods": payment_methods or [],
        "customers": customers or [],
        "users": users or [],
        "discounts": discounts or [],
        "open_bills": open_bills or [],
        "store_settings": store_settings,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/change_version")
async def get_change_version():
    """Return the current change_version counter for cross-device sync polling."""
    try:
        row = await fetch_one(
            "SELECT config_value FROM app_config WHERE config_key = 'change_version'"
        )
        version = int(row["config_value"]) if row else 0
    except Exception:
        version = 0
    return {"version": version}


@router.post("/change_version/bump")
async def bump_change_version_api():
    """Increment the change_version counter (called after writes)."""
    try:
        row = await fetch_one(
            "SELECT config_value FROM app_config WHERE config_key = 'change_version'"
        )
        if row:
            new_ver = int(row["config_value"]) + 1
            await execute(
                "UPDATE app_config SET config_value = %s WHERE config_key = 'change_version'",
                [str(new_ver)],
            )
        else:
            new_ver = 1
            await execute(
                "INSERT INTO app_config (config_key, config_value) VALUES ('change_version', '1')"
            )
        return {"version": new_ver}
    except Exception as e:
        return {"version": 0, "error": str(e)}


async def _safe(coro_func, *args):
    """Run a query safely — return [] on error instead of crashing."""
    try:
        return await coro_func(*args)
    except Exception:
        return []

