"""
Payments Router — /api/payments
Payment method CRUD.
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Body
from core.database import fetch_all, fetch_one, execute
from auth.security import get_current_user, get_optional_user

router = APIRouter()


@router.get("")
async def get_payment_methods(user: Optional[dict] = Depends(get_optional_user)):
    """GET /api/payments — list all payment methods."""
    rows = await fetch_all("SELECT * FROM payment_methods ORDER BY id")
    return {"methods": rows}



@router.post("")
async def create_payment_method(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/payments — create payment method."""
    mid = await execute(
        "INSERT INTO payment_methods (name, description, gateway_type, api_key, api_secret, merchant_id, is_online, active) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 1)",
        [body.get("name"), body.get("description", ""), body.get("gateway_type", "manual"),
         body.get("api_key"), body.get("api_secret"), body.get("merchant_id"), body.get("is_online", 0)],
    )
    return {"id": mid, "message": "Payment method created"}


@router.put("/{method_id}")
async def update_payment_method(method_id: int, body: dict = Body(...), user: dict = Depends(get_current_user)):
    """PUT /api/payments/{id} — update payment method fields."""
    existing = await fetch_one("SELECT * FROM payment_methods WHERE id = %s", [method_id])
    if not existing:
        return {"error": True, "message": "Payment method not found"}

    name = body.get("name", existing.get("name"))
    description = body.get("description", existing.get("description"))
    gateway_type = body.get("gateway_type", existing.get("gateway_type"))
    api_key = body.get("api_key", existing.get("api_key"))
    api_secret = body.get("api_secret", existing.get("api_secret"))
    merchant_id = body.get("merchant_id", existing.get("merchant_id"))
    is_online = body.get("is_online", existing.get("is_online"))
    active = body.get("active", existing.get("active", 1))

    await execute(
        "UPDATE payment_methods SET name = %s, description = %s, gateway_type = %s, "
        "api_key = %s, api_secret = %s, merchant_id = %s, is_online = %s, active = %s WHERE id = %s",
        [name, description, gateway_type, api_key, api_secret, merchant_id, is_online, active, method_id],
    )
    return {"message": "Payment method updated"}


@router.put("/{method_id}/toggle")
async def toggle_payment_method(method_id: int, user: dict = Depends(get_current_user)):
    """PUT /api/payments/{id}/toggle — toggle active status."""
    existing = await fetch_one("SELECT id, active FROM payment_methods WHERE id = %s", [method_id])
    if not existing:
        return {"error": True, "message": "Payment method not found"}

    new_active = 0 if existing.get("active") == 1 else 1
    await execute("UPDATE payment_methods SET active = %s WHERE id = %s", [new_active, method_id])
    return {"message": "Payment method status toggled", "active": new_active}


@router.delete("/{method_id}")
async def delete_payment_method(method_id: int, user: dict = Depends(get_current_user)):
    """DELETE /api/payments/{id}"""
    await execute("DELETE FROM payment_methods WHERE id = %s", [method_id])
    return {"message": "Payment method deleted"}


# ── Multi-Gateway Processing ─────────────────────────────────────

@router.post("/initiate")
async def initiate_gateway_payment(
    body: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    """POST /api/payments/initiate — initiate online payment via Paymob, Fawry, Vodafone Cash, or Tabby."""
    from services.payment_service import get_gateway_instance

    gateway_name = body.get("gateway") or body.get("method") or "paymob"
    amount = float(body.get("amount", 0.0))
    order_id = str(body.get("order_id") or body.get("order_number") or f"ORD-{int(datetime.now().timestamp())}")
    customer = body.get("customer") or {}

    if amount <= 0:
        return {"success": False, "message": "Amount must be greater than zero"}

    gateway = await get_gateway_instance(gateway_name)
    result = await gateway.initiate_payment(amount=amount, order_id=order_id, customer=customer)

    return {
        "success": result.success,
        "transaction_id": result.transaction_id,
        "reference_code": result.reference_code,
        "checkout_url": result.checkout_url,
        "message": result.message,
        "gateway": gateway_name,
        "amount": result.amount,
        "gateway_response": result.gateway_response,
    }


@router.get("/verify/{transaction_id}")
async def verify_gateway_payment(
    transaction_id: str,
    gateway: str = "paymob",
    user: dict = Depends(get_current_user),
):
    """GET /api/payments/verify/{transaction_id} — check transaction status."""
    from services.payment_service import get_gateway_instance

    gw = await get_gateway_instance(gateway)
    is_valid = await gw.verify_payment(transaction_id)
    return {
        "transaction_id": transaction_id,
        "gateway": gateway,
        "is_paid": is_valid,
        "status": "paid" if is_valid else "pending",
    }


@router.post("/webhook/{gateway}")
async def payment_webhook(
    gateway: str,
    body: dict = Body(...),
):
    """POST /api/payments/webhook/{gateway} — asynchronous payment gateway notification."""
    from services.payment_service import get_gateway_instance

    gw = await get_gateway_instance(gateway)
    # Check payload success
    is_success = body.get("success") is True or body.get("obj", {}).get("success") is True
    order_id = body.get("order_id") or body.get("obj", {}).get("order", {}).get("merchant_order_id")

    if is_success and order_id:
        # Mark sale as paid / update payment method
        await execute(
            "UPDATE sales SET method = %s WHERE order_number = %s",
            [f"{gateway.title()} (Online)", order_id],
        )

    return {"received": True, "status": "processed", "gateway": gateway}
