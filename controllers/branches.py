"""
Branches Router — /api/branches
Each tenant can have multiple branches.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, Body, HTTPException
from core.database import fetch_all, fetch_one, execute
from auth.security import get_current_user
from schemas.branch import BranchCreate, BranchUpdate, BranchOut

router = APIRouter()


def _require_admin(user: dict):
    if user.get("role") not in ("master_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("")
async def list_branches(user: dict = Depends(get_current_user)):
    """GET /api/branches — list branches scoped to tenant"""
    if user.get("role") == "master_admin":
        rows = await fetch_all("SELECT * FROM branches ORDER BY tenant_id, id")
    else:
        tenant_id = user.get("tenant_id")
        rows = await fetch_all(
            "SELECT * FROM branches WHERE tenant_id = %s ORDER BY id", [tenant_id]
        )
    for r in rows:
        if isinstance(r.get("created_at"), datetime):
            r["created_at"] = r["created_at"].isoformat()
    return {"branches": rows}


@router.get("/{branch_id}")
async def get_branch(branch_id: int, user: dict = Depends(get_current_user)):
    """GET /api/branches/{id}"""
    row = await fetch_one("SELECT * FROM branches WHERE id = %s", [branch_id])
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    if isinstance(row.get("created_at"), datetime):
        row["created_at"] = row["created_at"].isoformat()
    return {"branch": row}


@router.post("")
async def create_branch(body: BranchCreate, user: dict = Depends(get_current_user)):
    """POST /api/branches"""
    _require_admin(user)
    bid = await execute(
        "INSERT INTO branches (tenant_id, name, address, city, phone, manager_id, is_active, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
        [body.tenant_id, body.name, body.address, body.city,
         body.phone, body.manager_id, 1 if body.is_active else 0],
    )
    return {"id": bid, "message": "Branch created"}


@router.put("/{branch_id}")
async def update_branch(
    branch_id: int, body: BranchUpdate, user: dict = Depends(get_current_user)
):
    """PUT /api/branches/{id}"""
    _require_admin(user)
    fields, params = [], []
    updates = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        fields.append(f"{key} = %s")
        params.append(val)
    if fields:
        params.append(branch_id)
        await execute(
            f"UPDATE branches SET {', '.join(fields)}, updated_at = NOW() WHERE id = %s",
            params,
        )
    return {"message": "Branch updated"}


@router.delete("/{branch_id}")
async def delete_branch(branch_id: int, user: dict = Depends(get_current_user)):
    """DELETE /api/branches/{id}"""
    _require_admin(user)
    await execute("DELETE FROM branches WHERE id = %s", [branch_id])
    return {"message": "Branch deleted"}


@router.get("/{branch_id}/stats")
async def branch_stats(branch_id: int, user: dict = Depends(get_current_user)):
    """GET /api/branches/{id}/stats — branch performance summary"""
    users = await fetch_one(
        "SELECT COUNT(*) AS c FROM users WHERE branch_id = %s AND is_active = 1", [branch_id]
    )
    today_sales = await fetch_one(
        "SELECT COUNT(*) AS c, COALESCE(SUM(total_amount), 0) AS total "
        "FROM sales WHERE branch_id = %s AND DATE(date) = CURDATE()",
        [branch_id],
    )
    return {
        "user_count": users["c"] if users else 0,
        "today_sale_count": today_sales["c"] if today_sales else 0,
        "today_revenue": float(today_sales["total"]) if today_sales else 0.0,
    }
