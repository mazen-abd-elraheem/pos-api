"""
Sale Schemas — Offline-first with idempotency key support
"""
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class CartItem(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    price: float
    cost_price: float = 0.0
    notes: Optional[str] = None


class SaleCreate(BaseModel):
    # Idempotency: client sends a UUID to prevent duplicate submissions
    idempotency_key: str
    items: list[CartItem]
    total_amount: float
    total_items: int
    payment_method: str = "cash"
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    employee: Optional[str] = None
    table_id: Optional[int] = None
    order_number: Optional[str] = None
    discount_amount: float = 0.0
    vat_amount: float = 0.0
    notes: Optional[str] = None
    # Offline-first: client timestamp
    created_at_local: Optional[str] = None


class SaleOut(BaseModel):
    id: int
    order_number: str
    date: Optional[Any]
    products: Any
    total_items: int
    total_amount: float
    customer: Optional[str]
    employee: Optional[str]
    method: Optional[str]
    is_refunded: int
    tenant_id: Optional[int] = None
    branch_id: Optional[int] = None
    idempotency_key: Optional[str] = None

    class Config:
        from_attributes = True


class RefundCreate(BaseModel):
    sale_id: int
    refund_reason: str
    refund_type: str = "full"        # full, partial
    refund_method: str = "cash"
    products_refunded: Optional[Any] = None
    refund_amount: float
