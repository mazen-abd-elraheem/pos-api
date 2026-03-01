"""
Permissions Router — GET /api/permissions/batch
Mirrors PHP PermissionController.php
"""

from fastapi import APIRouter, Depends, Query

from database import fetch_all, fetch_one
from auth import get_current_user
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/batch")
async def batch_get(
    user_id: int | None = Query(None),
    user_data: dict = Depends(get_current_user),
):
    """GET /api/permissions/batch?user_id=X — all granted permissions for a user."""
    target_user_id = user_id or user_data["user_id"]

    user = await fetch_one("SELECT id, role FROM users WHERE id = %s", [target_user_id])
    if not user:
        return JSONResponse({"error": True, "message": "User not found"}, status_code=404)

    # Master admin gets ALL
    if user["role"] == "master_admin":
        all_perms = await fetch_all("SELECT name FROM permissions")
        return {
            "permissions": [p["name"] for p in all_perms],
            "role": "master_admin",
        }

    granted: dict[str, bool] = {}

    # Role-based permissions
    role_obj = await fetch_one("SELECT id FROM roles WHERE name = %s", [user["role"]])
    if role_obj:
        role_perms = await fetch_all(
            "SELECT p.name FROM role_permissions rp "
            "JOIN permissions p ON rp.permission_id = p.id "
            "WHERE rp.role_id = %s",
            [role_obj["id"]],
        )
        for rp in role_perms:
            granted[rp["name"]] = True

    # User-specific overrides
    user_perms = await fetch_all(
        "SELECT p.name, up.granted FROM user_permissions up "
        "JOIN permissions p ON up.permission_id = p.id "
        "WHERE up.user_id = %s",
        [target_user_id],
    )
    for up in user_perms:
        if up["granted"]:
            granted[up["name"]] = True
        else:
            granted.pop(up["name"], None)

    return {
        "permissions": list(granted.keys()),
        "role": user["role"],
    }


@router.get("/roles")
async def get_roles(user_data: dict = Depends(get_current_user)):
    """GET /api/permissions/roles — all roles."""
    rows = await fetch_all(
        "SELECT id, name, display_name, description, level "
        "FROM roles ORDER BY level ASC"
    )
    return {"roles": rows}
