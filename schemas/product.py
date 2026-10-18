"""
Product Schemas
"""
from pydantic import BaseModel
from typing import Optional


class ProductCreate(BaseModel):
    title: str
    price: float
    cost_price: float = 0.0
    barcode: Optional[str] = None
    stock: int = 0
    category_id: Optional[int] = None
    category: Optional[str] = None
    image: Optional[str] = "image.png"


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    price: Optional[float] = None
    cost_price: Optional[float] = None
    barcode: Optional[str] = None
    stock: Optional[int] = None
    category_id: Optional[int] = None
    category: Optional[str] = None
    image: Optional[str] = None


class ProductOut(BaseModel):
    id: int
    title: str
    price: float
    cost_price: float
    regular_price: float
    sale_price: float
    margin: float
    barcode: Optional[str]
    stock: int
    image: str
    category_id: Optional[int]
    category: Optional[str]
    # Multi-tenant fields (nullable until migration is done)
    tenant_id: Optional[int] = None
    branch_id: Optional[int] = None

    class Config:
        from_attributes = True
