"""
Branch Schemas — Multi-branch per tenant
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class BranchCreate(BaseModel):
    tenant_id: int
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    manager_id: Optional[int] = None
    is_active: bool = True


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    manager_id: Optional[int] = None
    is_active: Optional[bool] = None


class BranchOut(BaseModel):
    id: int
    tenant_id: int
    name: str
    address: Optional[str]
    city: Optional[str]
    phone: Optional[str]
    manager_id: Optional[int]
    is_active: bool
    created_at: Optional[datetime]

    class Config:
        from_attributes = True
