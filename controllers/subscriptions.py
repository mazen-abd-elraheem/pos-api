"""
Subscriptions Router — /api/subscriptions
Plan management, limit enforcement, status checks.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Body
from core.database import fetch_one, fetch_all, execute
from auth.security import get_current_user
from schemas.subscription import SubscriptionCheck, PLAN_LIMITS, SubscriptionStatus

router = APIRouter()


async def get_tenant_subscription(tenant_id: int) -> dict | None:
    """Fetch tenant subscription info from DB."""
    return await fetch_one(
        "SELECT id, plan, is_active, subscription_end FROM tenants WHERE id = %s",
        [tenant_id],
    )


async def check_tenant_active(tenant_id: int) -> SubscriptionStatus:
    """
    Returns subscription validity status.
    Used as a dependency in protected endpoints.
    """
    tenant = await get_tenant_subscription(tenant_id)
    if not tenant:
        return SubscriptionStatus(is_valid=False, reason="Tenant not found")
    if not tenant.get("is_active"):
        return SubscriptionStatus(is_valid=False, reason="Tenant suspended", plan=tenant["plan"])
    end = tenant.get("subscription_end")
    if end and isinstance(end, datetime) and end < datetime.now():
        return SubscriptionStatus(is_valid=False, reason="Subscription expired", plan=tenant["plan"])
    return SubscriptionStatus(is_valid=True, plan=tenant["plan"])


@router.get("/current")
@router.get("")
async def get_current_subscription(user: dict = Depends(get_current_user)):
    """GET /api/subscriptions/current — get subscription for current user's tenant or default."""
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        first_t = await fetch_one("SELECT id FROM tenants ORDER BY id ASC LIMIT 1")
        tenant_id = first_t["id"] if first_t else 1
    return await get_subscription(tenant_id, user)


@router.get("/{tenant_id}")
async def get_subscription(tenant_id: int, user: dict = Depends(get_current_user)):
    """GET /api/subscriptions/{tenant_id} — full subscription status"""
    tenant = await fetch_one(
        "SELECT id, plan, is_active, subscription_start, subscription_end FROM tenants WHERE id = %s",
        [tenant_id],
    )
    if not tenant:
        # Fallback to system license config if tenants table has no record
        end_conf = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'license_end_date' LIMIT 1")
        plan_conf = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'license_plan' LIMIT 1")
        plan_key = (plan_conf.get("config_value") if plan_conf else "free") or "free"
        end_str = end_conf.get("config_value") if end_conf else None
        end_dt = None
        if end_str:
            try:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        tenant = {
            "id": tenant_id,
            "plan": plan_key,
            "is_active": end_dt is not None and end_dt > datetime.now(),
            "subscription_start": None,
            "subscription_end": end_dt,
        }

    plan_key = tenant.get("plan", "free") or "free"
    limits = PLAN_LIMITS.get(plan_key, PLAN_LIMITS.get("trial", PLAN_LIMITS["free"]))

    end: datetime | None = tenant.get("subscription_end")
    days_remaining = None
    if end and isinstance(end, datetime):
        delta = end - datetime.now()
        days_remaining = max(0, delta.days)

    # Count current usage safely
    b_count, d_count, p_count, u_count = 0, 0, 0, 0
    try:
        row = await fetch_one("SELECT COUNT(*) AS c FROM branches WHERE is_active = 1")
        b_count = row["c"] if row else 0
    except Exception:
        pass

    try:
        row = await fetch_one("SELECT COUNT(*) AS c FROM devices WHERE is_active = 1")
        d_count = row["c"] if row else 0
    except Exception:
        pass

    try:
        row = await fetch_one("SELECT COUNT(*) AS c FROM products")
        p_count = row["c"] if row else 0
    except Exception:
        pass

    try:
        row = await fetch_one("SELECT COUNT(*) AS c FROM users WHERE is_active = 1")
        u_count = row["c"] if row else 0
    except Exception:
        pass

    return {
        "tenant_id": tenant_id,
        "plan": plan_key,
        "is_active": bool(tenant.get("is_active")),
        "subscription_end": end.isoformat() if isinstance(end, datetime) else end,
        "days_remaining": days_remaining,
        "limits": limits.model_dump(),
        "usage": {
            "branches": b_count,
            "devices": d_count,
            "products": p_count,
            "users": u_count,
        },
    }


@router.post("/{tenant_id}/upgrade")
async def upgrade_plan(
    tenant_id: int,
    body: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    """POST /api/subscriptions/{tenant_id}/upgrade — change plan"""
    if user.get("role") not in ("master_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin permissions required")

    new_plan = body.get("plan", "basic").lower()
    if new_plan not in PLAN_LIMITS:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {new_plan}")

    months = int(body.get("months", 1))
    end_date = datetime.now() + timedelta(days=30 * months)

    await execute(
        "UPDATE tenants SET plan = %s, subscription_end = %s, is_active = 1 WHERE id = %s",
        [new_plan, end_date, tenant_id],
    )
    # Also update app_config
    await execute(
        "UPDATE app_config SET config_value = %s WHERE config_key = 'license_plan'",
        [new_plan],
    )
    await execute(
        "UPDATE app_config SET config_value = %s WHERE config_key = 'license_end_date'",
        [end_date.strftime("%Y-%m-%d %H:%M:%S")],
    )
    return {"message": f"Plan upgraded to {new_plan}", "expires_at": end_date.isoformat()}



@router.post("/{tenant_id}/suspend")
async def suspend_tenant(tenant_id: int, user: dict = Depends(get_current_user)):
    """POST /api/subscriptions/{tenant_id}/suspend"""
    if user.get("role") != "master_admin":
        raise HTTPException(status_code=403, detail="Master admin only")
    await execute("UPDATE tenants SET is_active = 0 WHERE id = %s", [tenant_id])
    return {"message": "Tenant suspended"}


@router.get("/{tenant_id}/check")
async def check_limit(
    tenant_id: int,
    resource: str,
    user: dict = Depends(get_current_user),
):
    """GET /api/subscriptions/{tenant_id}/check?resource=products
    Returns whether tenant can add more of a resource.
    resource: products | branches | devices | users
    """
    tenant = await fetch_one(
        "SELECT plan, is_active FROM tenants WHERE id = %s", [tenant_id]
    )
    if not tenant or not tenant["is_active"]:
        return {"allowed": False, "reason": "Subscription inactive"}

    limits = PLAN_LIMITS.get(tenant["plan"], PLAN_LIMITS["free"])

    resource_map = {
        "products": ("products", limits.max_products),
        "branches": ("branches", limits.max_branches),
        "devices": ("devices", limits.max_devices),
        "users": ("users", limits.max_users),
    }

    if resource not in resource_map:
        raise HTTPException(status_code=400, detail="Unknown resource type")

    table, max_val = resource_map[resource]
    if max_val == -1:
        return {"allowed": True, "limit": "unlimited"}

    count_row = await fetch_one(
        f"SELECT COUNT(*) AS c FROM {table} WHERE tenant_id = %s", [tenant_id]
    )
    current = count_row["c"] if count_row else 0

    return {
        "allowed": current < max_val,
        "current": current,
        "limit": max_val,
        "plan": tenant["plan"],
    }
