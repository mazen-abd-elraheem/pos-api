"""
Auth Router — POST /api/auth/login, /api/auth/refresh
Now includes tenant_id, branch_id, and name in the JWT + response.
"""

from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.database import fetch_one, execute
from auth.security import generate_jwt, verify_password, hash_password, get_current_user

router = APIRouter()


@router.post("/login")
async def login(body: dict):
    """Authenticate user and return JWT with tenant/branch context."""
    username = body.get("username", "")
    password = body.get("password", "")

    if not username or not password:
        return JSONResponse(
            {"error": True, "message": "Username and password are required"},
            status_code=400,
        )

    user = await fetch_one("SELECT * FROM users WHERE username = %s OR email = %s", [username, username])
    if not user:
        return JSONResponse(
            {"error": True, "message": "Invalid credentials"}, status_code=401
        )

    if not user.get("is_active", 1):
        return JSONResponse(
            {"error": True, "message": "Account is disabled"}, status_code=403
        )

    # Verify password (bcrypt + legacy plain-text)
    if not verify_password(password, user["password"]):
        return JSONResponse(
            {"error": True, "message": "Invalid credentials"}, status_code=401
        )

    # Upgrade legacy plain-text to bcrypt silently
    if user["password"] == password:
        await execute(
            "UPDATE users SET password = %s WHERE id = %s",
            [hash_password(password), user["id"]],
        )

    # Update last_login timestamp
    await execute(
        "UPDATE users SET last_login = NOW() WHERE id = %s", [user["id"]]
    )

    tenant_id = user.get("tenant_id")
    branch_id = user.get("branch_id")
    name = user.get("name") or user["username"]

    token = generate_jwt(
        user_id=int(user["id"]),
        username=user["username"],
        role=user["role"],
        tenant_id=tenant_id,
        branch_id=branch_id,
        name=name,
    )

    # Fetch branch info if available
    branch_name = None
    if branch_id:
        branch = await fetch_one("SELECT name FROM branches WHERE id = %s", [branch_id])
        if branch:
            branch_name = branch["name"]

    # Fetch tenant info
    tenant_name = None
    if tenant_id:
        tenant = await fetch_one("SELECT name, plan, is_active FROM tenants WHERE id = %s", [tenant_id])
        if tenant:
            if not tenant.get("is_active"):
                return JSONResponse(
                    {"error": True, "message": "Your subscription is suspended. Please contact support."},
                    status_code=403,
                )
            tenant_name = tenant["name"]

    # Verify system license / subscription validity
    from services.license_service import get_license_status
    lic_status = await get_license_status(tenant_id)
    if not lic_status.get("is_active"):
        msg = lic_status.get("tamper_warning") or "System license has expired or is unactivated. Please activate a valid license key."
        return JSONResponse(
            {"error": True, "message": msg, "license_required": True},
            status_code=403,
        )

    return {
        "token": token,
        "user": {
            "id": int(user["id"]),
            "name": name,
            "username": user["username"],
            "role": user["role"],
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "tenant_name": tenant_name,
            "branch_name": branch_name,
            "is_active": bool(user.get("is_active", 1)),
        },
    }


@router.post("/refresh")
async def refresh(user_data: dict = Depends(get_current_user)):
    """Refresh token — re-fetch user from DB to get latest role/tenant."""
    user = await fetch_one("SELECT * FROM users WHERE id = %s", [user_data["user_id"]])
    if not user or not user.get("is_active"):
        return JSONResponse({"error": True, "message": "User not found or disabled"}, status_code=401)

    token = generate_jwt(
        user_id=int(user["id"]),
        username=user["username"],
        role=user["role"],
        tenant_id=user.get("tenant_id"),
        branch_id=user.get("branch_id"),
        name=user.get("name") or user["username"],
    )
    return {"token": token, "expires_in": 86400}


@router.get("/me")
async def me(user_data: dict = Depends(get_current_user)):
    """GET /api/auth/me — returns current user info from JWT."""
    user = await fetch_one(
        "SELECT id, name, username, role, tenant_id, branch_id, email, phone, is_active, last_login "
        "FROM users WHERE id = %s",
        [user_data["user_id"]],
    )
    if not user:
        return JSONResponse({"error": True, "message": "User not found"}, status_code=404)
    if isinstance(user.get("last_login"), datetime):
        user["last_login"] = user["last_login"].isoformat()
    return {"user": user}
