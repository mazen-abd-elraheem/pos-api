"""
Users Router — /api/users
Employee CRUD, password management.
"""
from fastapi import APIRouter, Depends, Body
from database import fetch_all, fetch_one, execute
from auth import get_current_user, hash_password

router = APIRouter()


@router.get("")
async def get_employees(user: dict = Depends(get_current_user)):
    """GET /api/users — list all active employees."""
    rows = await fetch_all(
        "SELECT id, name, username, role, is_active FROM users WHERE is_active = 1 ORDER BY id"
    )
    return {"users": rows}


@router.post("")
async def add_employee(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/users — create new employee."""
    pw_hash = hash_password(body["password"])
    uid = await execute(
        "INSERT INTO users (name, username, password, role, is_active) VALUES (%s, %s, %s, %s, 1)",
        [body["name"], body["username"], pw_hash, body.get("role", "cashier")],
    )
    return {"id": uid, "message": "Employee created"}


@router.put("/{user_id}")
async def update_user(user_id: int, body: dict = Body(...), user: dict = Depends(get_current_user)):
    """PUT /api/users/{id} — update user fields."""
    fields, params = [], []
    for key in ("name", "username", "role", "is_active"):
        if key in body:
            fields.append(f"{key} = %s")
            params.append(body[key])
    if fields:
        params.append(user_id)
        await execute(f"UPDATE users SET {', '.join(fields)} WHERE id = %s", params)
    return {"message": "User updated"}


@router.delete("/{user_id}")
async def delete_employee(user_id: int, user: dict = Depends(get_current_user)):
    """DELETE /api/users/{id} — soft-delete employee."""
    await execute("UPDATE users SET is_active = 0 WHERE id = %s", [user_id])
    return {"message": "Employee deleted"}


@router.put("/{user_id}/password")
async def change_password(user_id: int, body: dict = Body(...), user: dict = Depends(get_current_user)):
    """PUT /api/users/{id}/password"""
    pw_hash = hash_password(body["new_password"])
    await execute("UPDATE users SET password = %s WHERE id = %s", [pw_hash, user_id])
    return {"message": "Password changed"}
