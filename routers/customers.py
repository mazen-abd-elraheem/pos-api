"""
Customers Router — /api/customers
Mirrors PHP CustomerController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, execute
from auth import get_current_user

router = APIRouter()


@router.get("")
async def index(user_data: dict = Depends(get_current_user)):
    """GET /api/customers — list all customers."""
    customers = await fetch_all(
        "SELECT id, name, phone, email, loyalty_points, total_purchases "
        "FROM customers ORDER BY name ASC"
    )
    return {"customers": customers}


@router.post("")
async def store(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/customers — create a customer."""
    cid = await execute(
        "INSERT INTO customers (name, phone, email, loyalty_points, tenant_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        [
            body.get("name", ""),
            body.get("phone", ""),
            body.get("email", ""),
            body.get("loyalty_points", 0),
            body.get("tenant_id"),
        ],
    )
    return JSONResponse({"id": cid, "message": "Customer created"}, status_code=201)


@router.put("/{customer_id}")
async def update(customer_id: int, body: dict, user_data: dict = Depends(get_current_user)):
    """PUT /api/customers/{id} — update a customer."""
    allowed = ["name", "phone", "email", "loyalty_points", "total_purchases"]
    fields, values = [], []
    for f in allowed:
        if f in body:
            fields.append(f"{f} = %s")
            values.append(body[f])

    if not fields:
        return JSONResponse({"error": True, "message": "No fields to update"}, status_code=400)

    values.append(customer_id)
    await execute(f"UPDATE customers SET {', '.join(fields)} WHERE id = %s", values)
    return {"message": "Customer updated"}


@router.delete("/{customer_id}")
async def destroy(customer_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/customers/{id} — delete a customer."""
    await execute("DELETE FROM customers WHERE id = %s", [customer_id])
    return {"message": "Customer deleted"}
