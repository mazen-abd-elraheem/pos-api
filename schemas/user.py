"""
User Schemas
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    name: str
    username: str
    password: str
    role: str = "cashier"            # master_admin, admin, manager, cashier, waiter, kitchen
    email: Optional[str] = None
    phone: Optional[str] = None
    tenant_id: Optional[int] = None
    branch_id: Optional[int] = None
    manager_id: Optional[int] = None
    device_id: Optional[int] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    manager_id: Optional[int] = None
    branch_id: Optional[int] = None
    password: Optional[str] = None


class UserOut(BaseModel):
    id: int
    name: str
    username: str
    role: str
    email: Optional[str]
    phone: Optional[str]
    is_active: bool
    tenant_id: Optional[int]
    branch_id: Optional[int]
    manager_id: Optional[int]
    created_at: Optional[datetime]
    last_login: Optional[datetime]

    class Config:
        from_attributes = True
