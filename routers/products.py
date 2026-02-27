"""
Products Router — CRUD /api/products
Mirrors PHP ProductController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute
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
    """GET /api/products — list all products."""
    products = await fetch_all(
        "SELECT id, title, price, stock, barcode, category, image, "
        "cost_price, regular_price, sale_price, margin "
        "FROM products ORDER BY title ASC"
    )
    return {"products": products}


@router.get("/{product_id}")
async def show(product_id: int, user_data: dict = Depends(get_current_user)):
    """GET /api/products/{id} — get single product."""
    product = await fetch_one("SELECT * FROM products WHERE id = %s", [product_id])
    if not product:
        return JSONResponse({"error": True, "message": "Product not found"}, status_code=404)
    return {"product": product}


@router.post("")
async def store(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/products — create a product."""
    pid = await execute(
        "INSERT INTO products (title, price, stock, barcode, category, image, "
        "cost_price, regular_price, sale_price, margin, tenant_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            body.get("title", ""),
            body.get("price", 0),
            body.get("stock", 0),
            body.get("barcode", ""),
            body.get("category", ""),
            body.get("image", "image.png"),
            body.get("cost_price", 0),
            body.get("regular_price", 0),
            body.get("sale_price", 0),
            body.get("margin", 0),
            body.get("tenant_id"),
        ],
    )
    if body.get("stock", 0) > 0:
        await execute(
            "INSERT INTO stock_entries (name, product_id, quantity, report_id) "
            "VALUES (%s, %s, %s, %s)",
            [body.get("title", ""), pid, body.get("stock", 0), body.get("report_id", 0)],
        )
    await _bump_version()
    return JSONResponse({"id": pid, "message": "Product created"}, status_code=201)


@router.put("/{product_id}")
async def update(product_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """PUT /api/products/{id} — update a product."""
    allowed = [
        "title", "price", "stock", "barcode", "category", "image",
        "cost_price", "regular_price", "sale_price", "margin",
    ]
    fields, values = [], []
    for f in allowed:
        if f in body:
            fields.append(f"{f} = %s")
            values.append(body[f])

    if not fields:
        return JSONResponse({"error": True, "message": "No fields to update"}, status_code=400)

    values.append(product_id)
    await execute(f"UPDATE products SET {', '.join(fields)} WHERE id = %s", values)
    await _bump_version()
    return {"message": "Product updated"}


@router.delete("/{product_id}")
async def destroy(product_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/products/{id} — delete a product."""
    await execute("DELETE FROM products WHERE id = %s", [product_id])
    await _bump_version()
    return {"message": "Product deleted"}


@router.post("/{product_id}/stock/increment")
async def increment_stock(product_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/products/{id}/stock/increment — add stock."""
    quantity = body.get("quantity", 0)
    report_id = body.get("report_id", 0)
    product = await fetch_one("SELECT title, stock FROM products WHERE id = %s", [product_id])
    if not product:
        return JSONResponse({"error": True, "message": "Product not found"}, status_code=404)

    new_stock = (product["stock"] or 0) + quantity
    await execute("UPDATE products SET stock = %s WHERE id = %s", [new_stock, product_id])
    await execute(
        "INSERT INTO stock_entries (name, product_id, quantity, report_id) VALUES (%s, %s, %s, %s)",
        [product["title"], product_id, quantity, report_id],
    )
    await _bump_version()
    return {"message": f"Stock updated from {product['stock']} to {new_stock}", "new_stock": new_stock}


@router.post("/{product_id}/stock/decrement")
async def decrement_stock(product_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/products/{id}/stock/decrement — remove stock."""
    quantity = body.get("quantity", 0)
    report_id = body.get("report_id", 0)
    product = await fetch_one("SELECT title, stock FROM products WHERE id = %s", [product_id])
    if not product:
        return JSONResponse({"error": True, "message": "Product not found"}, status_code=404)

    if (product["stock"] or 0) < quantity:
        return JSONResponse({"error": True, "message": "Insufficient stock"}, status_code=400)

    new_stock = product["stock"] - quantity
    await execute("UPDATE products SET stock = %s WHERE id = %s", [new_stock, product_id])
    await execute(
        "INSERT INTO stock_exits (name, product_id, quantity, report_id) VALUES (%s, %s, %s, %s)",
        [product["title"], product_id, quantity, report_id],
    )
    await _bump_version()
    return {"message": f"Stock updated from {product['stock']} to {new_stock}", "new_stock": new_stock}


@router.post("/{product_id}/stock/set")
async def set_stock(product_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/products/{id}/stock/set — set stock to exact value (with movement tracking)."""
    quantity = body.get("quantity", 0)
    product = await fetch_one("SELECT title, stock FROM products WHERE id = %s", [product_id])
    if not product:
        return JSONResponse({"error": True, "message": "Product not found"}, status_code=404)

    diff = quantity - (product["stock"] or 0)
    await execute("UPDATE products SET stock = stock + %s WHERE id = %s", [diff, product_id])
    if diff > 0:
        await execute(
            "INSERT INTO stock_entries (name, product_id, quantity, report_id) VALUES (%s, %s, %s, %s)",
            [product["title"], product_id, diff, 0],
        )
    elif diff < 0:
        await execute(
            "INSERT INTO stock_exits (name, product_id, quantity, report_id) VALUES (%s, %s, %s, %s)",
            [product["title"], product_id, abs(diff), 0],
        )
    await _bump_version()
    return {"message": f"Stock set to {quantity}", "new_stock": quantity}
