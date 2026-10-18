"""
Auth Schemas — Login, Token, JWT payload
"""
from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    username: str
    password: str
    device_uuid: Optional[str] = None  # For device registration


class TokenResponse(BaseModel):
    token: str
    refresh_token: Optional[str] = None
    user: "UserTokenPayload"


class UserTokenPayload(BaseModel):
    user_id: int
    username: str
    name: str
    role: str
    tenant_id: Optional[int] = None
    branch_id: Optional[int] = None
    permissions: list[str] = []


class RefreshTokenRequest(BaseModel):
    refresh_token: str


TokenResponse.model_rebuild()
