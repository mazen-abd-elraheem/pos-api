"""
Sales Router — /api/sales
Complete sale transaction processing with shelf-aware stock deduction,
recipe ingredient tracking, and atomic rollback.
"""

import json
import random
import string
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute, execute_transaction
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
async def index(
    date: str | None = Query(None),
    limit: int = Query(100, le=500),
    user_data: dict = Depends(get_current_user),
):
    """GET /api/sales — list sales, optionally filtered by date."""
    if date:
        sales = await fetch_all(
            "SELECT * FROM sales WHERE date LIKE %s ORDER BY id DESC LIMIT %s",
            [f"%{date}%", limit],
        )
    else:
        sales = await fetch_all(
            "SELECT * FROM sales ORDER BY id DESC LIMIT %s", [limit]
        )
    return {"sales": sales}


@router.post("")
async def store(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/sales — full sale transaction with shelf-aware deduction.

    Handles: sale record, shelf deduction, main stock deduction,
    recipe ingredient deduction, stock movements — all atomically.
    """
    cart = body.get("items") or body.get("products") or []
    if not cart:
        return JSONResponse({"error": True, "message": "No items in cart"}, status_code=400)

    order_number = body.get("order_number") or (
        f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1, 9999):04d}"
    )

    products_json = json.dumps(cart, ensure_ascii=False)
    total_items = body.get("total_items") or sum(item.get("quantity", 1) for item in cart)
    report_id = body.get("report_id")
    employee = body.get("employee") or user_data.get("username", "Unknown")

    queries: list[tuple[str, list]] = []

    # 1. Insert sale record
    queries.append((
        "INSERT INTO sales (order_number, date, time, products, total_items, total_amount, "
        "report_id, customer, employee, method, is_refunded, tenant_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s)",
        [
            order_number,
            body.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            body.get("time") or datetime.now().strftime("%H:%M:%S"),
            products_json,
            total_items,
            body.get("total_amount", 0),
            report_id,
            body.get("customer"),
            employee,
            body.get("method", "Cash"),
            body.get("tenant_id"),
        ],
    ))

    # 2. Batch-load all products for stock check
    cart_ids = [item.get("product_id") or item.get("id") for item in cart if item.get("product_id") or item.get("id")]
    if cart_ids:
        placeholders = ",".join(["%s"] * len(cart_ids))
        products = await fetch_all(
            f"SELECT id, title, stock FROM products WHERE id IN ({placeholders})", cart_ids
        )
        products_map = {p["id"]: p for p in products}
    else:
        products_map = {}

    # 3. Load shelves for shelf-aware deduction
    shelves = await fetch_all(
        "SELECT id, product_id, current_quantity FROM shelves WHERE product_id IS NOT NULL AND current_quantity > 0 ORDER BY id"
    ) if cart_ids else []
    shelves_by_product = {}
    for s in shelves:
        shelves_by_product.setdefault(s["product_id"], []).append(s)

    # 4. Process each cart item: shelf deduction → main stock deduction
    for item in cart:
        product_id = item.get("product_id") or item.get("id")
        quantity = item.get("quantity", 1)
        product = products_map.get(product_id)

        if not product:
            return JSONResponse(
                {"error": True, "message": f"Product not found: {item.get('name', product_id)}"},
                status_code=400
            )

        remaining = quantity

        # Deduct from shelves first
        product_shelves = shelves_by_product.get(product_id, [])
        for shelf in product_shelves:
            if remaining <= 0:
                break
            available = shelf["current_quantity"] or 0
            deduct = min(remaining, available)
            if deduct > 0:
                queries.append((
                    "UPDATE shelves SET current_quantity = current_quantity - %s WHERE id = %s",
                    [deduct, shelf["id"]]
                ))
                shelf["current_quantity"] -= deduct  # Track in-memory
                remaining -= deduct

        # Deduct remainder from main stock
        if remaining > 0:
            if (product["stock"] or 0) < remaining:
                return JSONResponse(
                    {"error": True, "message": f"Insufficient stock for {product['title']}"},
                    status_code=400
                )
            queries.append((
                "UPDATE products SET stock = stock - %s WHERE id = %s",
                [remaining, product_id]
            ))

        # Record stock exit
        queries.append((
            "INSERT INTO stock_exits (name, product_id, quantity, report_id) VALUES (%s, %s, %s, %s)",
            [product["title"], product_id, quantity, report_id or 0]
        ))

    # 5. Recipe ingredient deduction
    if cart_ids:
        placeholders = ",".join(["%s"] * len(cart_ids))
        recipe_items = await fetch_all(
            f"SELECT product_id, ingredient_id, quantity_needed FROM recipe_items WHERE product_id IN ({placeholders})",
            cart_ids
        )
    else:
        recipe_items = []

    if recipe_items:
        ingredient_ids = list({ri["ingredient_id"] for ri in recipe_items if ri["ingredient_id"]})
        if ingredient_ids:
            placeholders = ",".join(["%s"] * len(ingredient_ids))
            ingredients = await fetch_all(
                f"SELECT id, name, current_stock, unit FROM ingredients WHERE id IN ({placeholders})",
                ingredient_ids
            )
            ingredients_map = {ing["id"]: ing for ing in ingredients}
        else:
            ingredients_map = {}

        # Group recipe items by product
        cart_qty_map = {(item.get("product_id") or item.get("id")): item.get("quantity", 1) for item in cart}

        for ri in recipe_items:
            ingredient = ingredients_map.get(ri["ingredient_id"])
            if not ingredient:
                continue

            required_qty = ri["quantity_needed"] * cart_qty_map.get(ri["product_id"], 1)
            if ingredient["current_stock"] < required_qty:
                return JSONResponse(
                    {"error": True, "message": f"Insufficient ingredient: {ingredient['name']}"},
                    status_code=400
                )

            queries.append((
                "UPDATE ingredients SET current_stock = current_stock - %s WHERE id = %s",
                [required_qty, ingredient["id"]]
            ))
            queries.append((
                "INSERT INTO ingredient_stock_movements (ingredient_id, movement_type, quantity, user) "
                "VALUES (%s, 'deduction', %s, %s)",
                [ingredient["id"], required_qty, employee]
            ))
            ingredient["current_stock"] -= required_qty  # Track in-memory

    # 6. Execute everything atomically
    try:
        sale_id = await execute_transaction(queries)
        await _bump_version()
        return JSONResponse(
            {"id": sale_id, "order_number": order_number, "message": "Sale recorded"},
            status_code=201,
        )
    except Exception as e:
        return JSONResponse(
            {"error": True, "message": f"Failed to record sale: {str(e)}"},
            status_code=500,
        )


@router.get("/report")
async def report(
    start_date: str = Query(default_factory=lambda: datetime.now().strftime("%Y-%m-%d")),
    end_date: str = Query(default_factory=lambda: datetime.now().strftime("%Y-%m-%d")),
    user_data: dict = Depends(get_current_user),
):
    """GET /api/sales/report — sales summary for a date range."""
    summary = await fetch_one(
        "SELECT COUNT(*) as total_sales, COALESCE(SUM(total_amount), 0) as total_revenue "
        "FROM sales WHERE date BETWEEN %s AND %s",
        [start_date, end_date],
    )

    payment_breakdown = await fetch_all(
        "SELECT method, COUNT(*) as count, SUM(total_amount) as total "
        "FROM sales WHERE date BETWEEN %s AND %s GROUP BY method",
        [start_date, end_date],
    )

    return {
        "summary": summary,
        "payment_breakdown": payment_breakdown,
        "period": {"start": start_date, "end": end_date},
    }
