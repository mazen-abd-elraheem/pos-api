"""
Sales Router — /api/sales
Mirrors PHP SaleController.php
"""

import json
import random
import string
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute_transaction
from auth import get_current_user

router = APIRouter()


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
    """POST /api/sales — record a sale with stock deduction (transactional)."""
    order_number = body.get("order_number") or (
        f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1, 9999):04d}"
    )

    items = body.get("items") or body.get("products") or []
    products_json = json.dumps(items, ensure_ascii=False)
    total_items = body.get("total_items") or len(items)

    queries: list[tuple[str, list]] = []

    # 1. Insert sale
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
            body.get("report_id"),
            body.get("customer"),
            body.get("employee") or user_data.get("username", "Unknown"),
            body.get("method", "Cash"),
            body.get("tenant_id"),
        ],
    ))

    # 2. Deduct stock for each item
    for item in items:
        product_id = item.get("product_id") or item.get("id")
        quantity = item.get("quantity", 1)
        if product_id:
            queries.append((
                "UPDATE products SET stock = stock - %s WHERE id = %s AND stock >= %s",
                [quantity, product_id, quantity],
            ))

    try:
        sale_id = await execute_transaction(queries)
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
