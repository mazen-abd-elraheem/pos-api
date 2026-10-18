"""
Subscription / Plan Schemas
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PlanLimits(BaseModel):
    """Defines what each plan allows"""
    plan: str
    max_branches: int
    max_devices: int
    max_products: int
    max_users: int
    has_kitchen_display: bool
    has_advanced_reports: bool
    has_inventory_ledger: bool
    has_api_access: bool


# Plan definitions
PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        plan="free",
        max_branches=1,
        max_devices=1,
        max_products=100,
        max_users=2,
        has_kitchen_display=False,
        has_advanced_reports=False,
        has_inventory_ledger=False,
        has_api_access=False,
    ),
    "trial": PlanLimits(
        plan="trial",
        max_branches=2,
        max_devices=3,
        max_products=300,
        max_users=5,
        has_kitchen_display=True,
        has_advanced_reports=True,
        has_inventory_ledger=True,
        has_api_access=False,
    ),
    "basic": PlanLimits(
        plan="basic",
        max_branches=2,
        max_devices=3,
        max_products=500,
        max_users=10,
        has_kitchen_display=True,
        has_advanced_reports=False,
        has_inventory_ledger=True,
        has_api_access=False,
    ),
    "pro": PlanLimits(
        plan="pro",
        max_branches=10,
        max_devices=20,
        max_products=-1,     # unlimited
        max_users=-1,        # unlimited
        has_kitchen_display=True,
        has_advanced_reports=True,
        has_inventory_ledger=True,
        has_api_access=True,
    ),
    "enterprise": PlanLimits(
        plan="enterprise",
        max_branches=-1,
        max_devices=-1,
        max_products=-1,
        max_users=-1,
        has_kitchen_display=True,
        has_advanced_reports=True,
        has_inventory_ledger=True,
        has_api_access=True,
    ),
}


class SubscriptionCheck(BaseModel):
    tenant_id: int
    plan: str
    is_active: bool
    subscription_end: Optional[datetime]
    days_remaining: Optional[int]
    limits: PlanLimits


class SubscriptionStatus(BaseModel):
    is_valid: bool
    reason: Optional[str] = None
    plan: Optional[str] = None
