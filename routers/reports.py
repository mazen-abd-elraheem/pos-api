"""
Reports Router — extends /api/sales with report-specific endpoints.
Handles report CRUD, totals, stock entries/exits for reports.
"""

from datetime import datetime
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, Body
from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


# ── Report CRUD ──

@router.get("")
async def get_reports(user: dict = Depends(get_current_user)):
    """GET /api/reports — list all reports."""
    rows = await fetch_all(
        "SELECT id, name, date, cashier, employee FROM sales_reports ORDER BY id DESC"
    )
    return {"reports": rows}


@router.post("")
async def create_report(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/reports — create a new daily report."""
    day = body.get("day")
    employee = body.get("employee", "admin")
    report_id = await execute(
        "INSERT INTO sales_reports (name, date, cashier, employee) VALUES (%s, %s, 'admin', %s)",
        [f"report_{day}", day, employee],
    )

    initial_entry = body.get("initial_entry")
    if initial_entry:
        for item in initial_entry:
            product = await fetch_one("SELECT id FROM products WHERE title = %s", [item["name"]])
            if product:
                await execute(
                    "INSERT INTO stock_entries (name, quantity, product_id, report_id) VALUES (%s, %s, %s, %s)",
                    [item["name"], item.get("stock", 0), product["id"], report_id],
                )

    report = await fetch_one("SELECT id, name, date, cashier, employee FROM sales_reports WHERE id = %s", [report_id])
    return {"report": report}


@router.get("/{report_id}")
async def get_report(report_id: int, user: dict = Depends(get_current_user)):
    """GET /api/reports/{id} — get a single report."""
    report = await fetch_one("SELECT id, name, date, cashier, employee FROM sales_reports WHERE id = %s", [report_id])
    if not report:
        return {"report": None}
    return {"report": report}


@router.get("/by-date/{day}")
async def get_report_by_date(day: str, user: dict = Depends(get_current_user)):
    """GET /api/reports/by-date/{day} — get report by date."""
    # Try exact match first
    report = await fetch_one("SELECT id, name, date, cashier, employee FROM sales_reports WHERE date = %s", [day])
    if not report:
        # Try converting DD-MM-YYYY → YYYY-MM-DD for MySQL date columns
        try:
            parts = day.split("-")
            if len(parts) == 3 and len(parts[0]) == 2:
                converted = f"{parts[2]}-{parts[1]}-{parts[0]}"
                report = await fetch_one(
                    "SELECT id, name, date, cashier, employee FROM sales_reports WHERE date = %s", [converted]
                )
        except Exception:
            pass
    if not report:
        # Also try matching by report name (legacy format: report_DD-MM-YYYY or report_YYYY-MM-DD)
        report = await fetch_one(
            "SELECT id, name, date, cashier, employee FROM sales_reports WHERE name LIKE %s",
            [f"%{day}%"]
        )
    return {"report": report}


@router.delete("/{report_id}")
async def delete_report(report_id: int, user: dict = Depends(get_current_user)):
    """DELETE /api/reports/{id}"""
    await execute("DELETE FROM sales_reports WHERE id = %s", [report_id])
    return {"success": True}


@router.delete("/by-date/{day}")
async def remove_report_by_date(day: str, user: dict = Depends(get_current_user)):
    """DELETE /api/reports/by-date/{day}"""
    await execute("DELETE FROM sales_reports WHERE date = %s", [day])
    return {"success": True}


# ── Totals ──

@router.get("/{report_id}/total")
async def report_total(report_id: int = None, day: str = Query(None), user: dict = Depends(get_current_user)):
    """GET /api/reports/{id}/total — total monetary value."""
    if day:
        row = await fetch_one(
            "SELECT COALESCE(SUM(ps.total_amount), 0) AS total FROM product_sales ps "
            "JOIN sales_reports sr ON ps.report_id = sr.id WHERE sr.date = %s", [day]
        )
    else:
        row = await fetch_one(
            "SELECT COALESCE(SUM(ps.total_amount), 0) AS total FROM product_sales ps WHERE ps.report_id = %s",
            [report_id]
        )
    return {"total": float(row["total"]) if row else 0.0}


# ── Stock History ──

@router.get("/{report_id}/stock-entries")
async def stock_entries(report_id: int, user: dict = Depends(get_current_user)):
    """GET /api/reports/{id}/stock-entries"""
    rows = await fetch_all(
        "SELECT name AS product_name, SUM(quantity) AS quantity "
        "FROM stock_entries WHERE report_id = %s GROUP BY name",
        [report_id]
    )
    return {"entries": {r["product_name"]: int(r["quantity"]) for r in rows}}


@router.get("/{report_id}/stock-exits")
async def stock_exits(report_id: int, user: dict = Depends(get_current_user)):
    """GET /api/reports/{id}/stock-exits"""
    rows = await fetch_all(
        "SELECT name AS product_name, SUM(quantity) AS quantity "
        "FROM stock_exits WHERE report_id = %s GROUP BY name",
        [report_id]
    )
    return {"exits": {r["product_name"]: int(r["quantity"]) for r in rows}}


@router.get("/{report_id}/stock-history")
async def stock_history(report_id: int, user: dict = Depends(get_current_user)):
    """GET /api/reports/{id}/stock-history — full stock in/out analysis."""
    entries = await fetch_all(
        "SELECT product_id, name, SUM(quantity) AS qty FROM stock_entries WHERE report_id = %s GROUP BY product_id, name",
        [report_id]
    )
    exits = await fetch_all(
        "SELECT product_id, name, SUM(quantity) AS qty FROM stock_exits WHERE report_id = %s GROUP BY product_id, name",
        [report_id]
    )

    entry_map = {r["product_id"]: int(r["qty"]) for r in entries}
    exit_map = {r["product_id"]: int(r["qty"]) for r in exits}
    product_ids = list(set(list(entry_map.keys()) + list(exit_map.keys())))

    if not product_ids:
        return {"history": []}

    placeholders = ",".join(["%s"] * len(product_ids))
    products = await fetch_all(
        f"SELECT id, title, stock, category FROM products WHERE id IN ({placeholders})",
        product_ids
    )

    history = []
    for p in products:
        entry_qty = entry_map.get(p["id"], 0)
        exit_qty = exit_map.get(p["id"], 0)
        history.append({
            "name": p["title"],
            "initial_stock": (p["stock"] or 0) + exit_qty - entry_qty,
            "entry": entry_qty,
            "exit": exit_qty,
            "current_stock": p["stock"] or 0,
            "category": p["category"] or "Uncategorized",
        })

    return {"history": history}


@router.get("/{report_id}/stock-report")
async def stock_report(report_id: int, user: dict = Depends(get_current_user)):
    """GET /api/reports/{id}/stock-report"""
    row = await fetch_one("SELECT history FROM stock_reports WHERE id = %s", [report_id])
    if row and row.get("history"):
        import json
        try:
            return {"history": json.loads(row["history"]) if isinstance(row["history"], str) else row["history"]}
        except Exception:
            return {"history": []}
    return {"history": []}
