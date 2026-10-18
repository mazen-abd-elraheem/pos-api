"""
Users Router — /api/users
Employee CRUD, password management.
"""
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth.security import get_current_user, get_optional_user
from core.database import get_db
from models.user import UserCreate, UserUpdate, PasswordChange
from services.user import UserService

router = APIRouter()


@router.get("")
async def get_employees(user: Optional[dict] = Depends(get_optional_user), db: AsyncSession = Depends(get_db)):
    """GET /api/users — list all active employees."""
    svc = UserService(db)
    users = await svc.get_active_employees()
    return {"users": [{"id": u.id, "name": u.name, "username": u.username, "role": u.role, "is_active": u.is_active} for u in users]}



@router.post("")
async def add_employee(body: UserCreate, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """POST /api/users — create new employee."""
    svc = UserService(db)
    uid = await svc.create_employee(body.model_dump())
    return {"id": uid, "message": "Employee created"}


@router.put("/{user_id}")
async def update_user(user_id: int, body: UserUpdate, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """PUT /api/users/{id} — update user fields."""
    svc = UserService(db)
    await svc.update_employee(user_id, body.model_dump(exclude_unset=True))
    return {"message": "User updated"}


@router.delete("/{user_id}")
async def delete_employee(user_id: int, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """DELETE /api/users/{id} — soft-delete employee."""
    svc = UserService(db)
    await svc.delete_employee(user_id)
    return {"message": "Employee deleted"}


@router.put("/{user_id}/password")
async def change_password(user_id: int, body: PasswordChange, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """PUT /api/users/{id}/password"""
    svc = UserService(db)
    await svc.change_password(user_id, body.new_password)
    return {"message": "Password changed"}
