"""
Tables Router — /api/tables
Mirrors PHP TableController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, execute
from auth import get_current_user

router = APIRouter()


@router.get("")
async def index(user_data: dict = Depends(get_current_user)):
    """GET /api/tables — list all tables."""
    tables = await fetch_all(
        "SELECT id, number, capacity, status, current_order_id "
        "FROM tables ORDER BY number ASC"
    )
    return {"tables": tables}


@router.put("/{table_id}")
async def update(table_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """PUT /api/tables/{id} — update a table."""
    allowed = ["number", "capacity", "status", "current_order_id"]
    fields, values = [], []
    for f in allowed:
        if f in body:
            fields.append(f"{f} = %s")
            values.append(body[f])

    if not fields:
        return JSONResponse(
            {"error": True, "message": "No fields to update"}, status_code=400
        )

    values.append(table_id)
    await execute(f"UPDATE `tables` SET {', '.join(fields)} WHERE id = %s", values)
    return {"message": "Table updated"}
