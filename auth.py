"""
POS API — JWT Authentication
Same HS256 algorithm and payload structure as PHP auth.php.
Tokens are interchangeable between PHP and FastAPI.
"""

import time
import hmac
import hashlib
import json
import base64
import logging
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request
from config import settings

logger = logging.getLogger("auth")


# ──────────────────────────────────────────────
# Base64url helpers (match PHP base64url_encode/decode)
# ──────────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


# ──────────────────────────────────────────────
# JWT generation / verification
# ──────────────────────────────────────────────

def generate_jwt(user_id: int, username: str, role: str) -> str:
    """Generate a JWT token (same format as PHP)."""
    header = _b64url_encode(json.dumps({"typ": "JWT", "alg": "HS256"}).encode())
    payload_data = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + settings.JWT_EXPIRY,
    }
    payload = _b64url_encode(json.dumps(payload_data).encode())
    signature = _b64url_encode(
        hmac.new(settings.JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def verify_jwt(token: str) -> Optional[dict]:
    """Verify a JWT token and return the payload, or None if invalid."""
    parts = token.split(".")
    if len(parts) != 3:
        return None

    header, payload, signature = parts

    expected_sig = _b64url_encode(
        hmac.new(settings.JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected_sig, signature):
        return None

    try:
        data = json.loads(_b64url_decode(payload))
    except Exception:
        return None

    if data.get("exp", 0) < int(time.time()):
        return None

    return data


# ──────────────────────────────────────────────
# Password verification (matches PHP logic)
# ──────────────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password. Supports bcrypt and legacy plain-text."""
    # Try bcrypt first
    try:
        if bcrypt.checkpw(plain_password.encode(), hashed_password.encode()):
            return True
    except (ValueError, Exception):
        pass

    # Legacy plain-text match
    if plain_password == hashed_password:
        return True

    return False


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


# ──────────────────────────────────────────────
# FastAPI dependency — extract current user from token
# ──────────────────────────────────────────────

async def get_current_user(request: Request) -> dict:
    """FastAPI dependency: extract and validate JWT from Authorization header."""
    auth_header = request.headers.get("Authorization", "")

    if not auth_header:
        raise HTTPException(status_code=401, detail="Authorization header required")

    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format. Use: Bearer <token>")

    token = auth_header[7:]
    user_data = verify_jwt(token)

    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user_data
