"""
Products Router — CRUD /api/products
Mirrors PHP ProductController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


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
    return {"message": "Product updated"}


@router.delete("/{product_id}")
async def destroy(product_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/products/{id} — delete a product."""
    await execute("DELETE FROM products WHERE id = %s", [product_id])
    return {"message": "Product deleted"}
