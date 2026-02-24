"""
Auth Router — POST /api/auth/login, /api/auth/refresh
Mirrors PHP AuthController.php
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_one, execute
from auth import generate_jwt, verify_password, hash_password, get_current_user

router = APIRouter()


@router.post("/login")
async def login(body: dict):
    """Authenticate user and return JWT token."""
    username = body.get("username", "")
    password = body.get("password", "")

    if not username or not password:
        return JSONResponse(
            {"error": True, "message": "Username and password are required"},
            status_code=400,
        )

    user = await fetch_one("SELECT * FROM users WHERE username = %s", [username])
    if not user:
        return JSONResponse(
            {"error": True, "message": "Invalid credentials"}, status_code=401
        )

    # Verify password (bcrypt + legacy plain-text)
    valid = verify_password(password, user["password"])
    if not valid:
        return JSONResponse(
            {"error": True, "message": "Invalid credentials"}, status_code=401
        )

    # Upgrade legacy plain-text to bcrypt
    if user["password"] == password:
        hashed = hash_password(password)
        await execute("UPDATE users SET password = %s WHERE id = %s", [hashed, user["id"]])

    token = generate_jwt(user["id"], user["username"], user["role"])

    return {
        "token": token,
        "user": {
            "id": int(user["id"]),
            "name": user.get("name", user["username"]),
            "username": user["username"],
            "role": user["role"],
        },
    }


@router.post("/refresh")
async def refresh(user_data: dict = Depends(get_current_user)):
    """Refresh an existing valid token."""
    token = generate_jwt(user_data["user_id"], user_data["username"], user_data["role"])
    return {"token": token, "expires_in": 86400}
