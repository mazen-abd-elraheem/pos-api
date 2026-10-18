from pydantic import BaseModel, Field
from typing import Optional

class UserCreate(BaseModel):
    name: str
    username: str
    password: str
    role: Optional[str] = "cashier"

class UserUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[int] = None

class PasswordChange(BaseModel):
    new_password: str
