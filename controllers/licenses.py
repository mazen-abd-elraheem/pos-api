"""
Licenses Router — /api/licenses
Activation, verification, edition status, and hardware binding.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from auth.security import get_current_user, get_optional_user
from services.license_service import (
    activate_license,
    get_license_status,
    validate_license_key,
    generate_license_key,
)

router = APIRouter()


@router.get("/status")
async def license_status(user_data: Optional[dict] = Depends(get_optional_user)):
    """GET /api/licenses/status — retrieve current plan, limits, and hardware UUID."""
    tenant_id = user_data.get("tenant_id") if user_data else None
    status = await get_license_status(tenant_id)
    return status


@router.post("/activate")
async def license_activate(
    body: dict = Body(...),
    user_data: Optional[dict] = Depends(get_optional_user),
):
    """POST /api/licenses/activate — activate a signed license key."""
    key = body.get("license_key") or body.get("key")
    if not key:
        raise HTTPException(status_code=400, detail="license_key is required")

    tenant_id = user_data.get("tenant_id") if user_data else None
    res = await activate_license(key, tenant_id=tenant_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Activation failed"))
    return res


@router.post("/trial")
async def start_trial(user_data: Optional[dict] = Depends(get_optional_user)):
    """POST /api/licenses/trial — activate 14-day free trial license for unactivated system."""
    tenant_id = user_data.get("tenant_id") if user_data else None
    current_status = await get_license_status(tenant_id)
    if current_status.get("is_active"):
        return {
            "success": True,
            "message": "System already has an active license",
            **current_status
        }
    if current_status.get("trial_used"):
        raise HTTPException(
            status_code=400,
            detail="The 14-day free trial has already been used on this terminal. Please activate with a commercial license key."
        )

    key = generate_license_key(days=14, plan="trial")
    res = await activate_license(key, tenant_id=tenant_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Trial activation failed"))
    return res


@router.post("/verify")
async def license_verify(
    body: dict = Body(...),
    user_data: Optional[dict] = Depends(get_optional_user),
):
    """POST /api/licenses/verify — inspect key signature and plan without activating."""
    key = body.get("license_key") or body.get("key")
    if not key:
        raise HTTPException(status_code=400, detail="license_key is required")

    res = validate_license_key(key)
    return res


@router.post("/generate")
async def license_generate(
    body: dict = Body(...),
    user_data: dict = Depends(get_current_user),
):
    """POST /api/licenses/generate — admin tool to generate a signed license key."""
    # Only master_admin or admin can generate keys
    role = user_data.get("role", "")
    if role not in ("master_admin", "admin"):
        raise HTTPException(status_code=403, detail="Permission denied")

    days = int(body.get("days", 30))
    plan = body.get("plan", "basic")
    key = generate_license_key(days, plan)
    return {
        "success": True,
        "license_key": key,
        "plan": plan,
        "days": days,
    }

