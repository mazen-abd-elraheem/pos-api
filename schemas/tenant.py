"""
Tenant Schemas — Multi-tenant SaaS
"""
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class TenantCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    business_type: str = "restaurant"   # restaurant, cafe, supermarket, barber, pharmacy
    owner_name: str
    owner_email: Optional[str] = None
    owner_phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    plan: str = "basic"                  # free, basic, pro, enterprise


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    owner_phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    is_active: Optional[bool] = None
    plan: Optional[str] = None


class TenantOut(BaseModel):
    id: int
    name: str
    slug: Optional[str]
    business_type: Optional[str]
    owner_name: Optional[str]
    owner_email: Optional[str]
    owner_phone: Optional[str]
    address: Optional[str]
    city: Optional[str]
    plan: str
    is_active: bool
    subscription_start: Optional[datetime]
    subscription_end: Optional[datetime]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True
