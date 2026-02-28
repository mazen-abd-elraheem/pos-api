"""
Payments Router — /api/payments
Payment method CRUD.
"""
from fastapi import APIRouter, Depends, Body
from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


@router.get("")
async def get_payment_methods(user: dict = Depends(get_current_user)):
    """GET /api/payments — list all payment methods."""
    rows = await fetch_all("SELECT * FROM payment_methods ORDER BY id")
    return {"methods": rows}


@router.post("")
async def create_payment_method(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/payments — create payment method."""
    mid = await execute(
        "INSERT INTO payment_methods (name, description, gateway_type, api_key, api_secret, merchant_id, is_online) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        [body.get("name"), body.get("description", ""), body.get("gateway_type", "manual"),
         body.get("api_key"), body.get("api_secret"), body.get("merchant_id"), body.get("is_online", 0)],
    )
    return {"id": mid, "message": "Payment method created"}


@router.delete("/{method_id}")
async def delete_payment_method(method_id: int, user: dict = Depends(get_current_user)):
    """DELETE /api/payments/{id}"""
    await execute("DELETE FROM payment_methods WHERE id = %s", [method_id])
    return {"message": "Payment method deleted"}
