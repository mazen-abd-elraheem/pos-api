"""
Tenants Router — /api/tenants
Multi-tenant management, employee hierarchy, performance tracking.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, Body
from database import fetch_all, fetch_one, execute
from auth import get_current_user, hash_password

router = APIRouter()


@router.get("")
async def get_all_tenants(user: dict = Depends(get_current_user)):
    """GET /api/tenants"""
    rows = await fetch_all("SELECT * FROM tenants ORDER BY id")
    for r in rows:
        for k in ("created_at", "updated_at"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].isoformat()
    return {"tenants": rows}


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: int, user: dict = Depends(get_current_user)):
    """GET /api/tenants/{id}"""
    row = await fetch_one("SELECT * FROM tenants WHERE id = %s", [tenant_id])
    if row:
        for k in ("created_at", "updated_at"):
            if isinstance(row.get(k), datetime):
                row[k] = row[k].isoformat()
    return {"tenant": row}


@router.get("/{tenant_id}/stats")
async def tenant_stats(tenant_id: int, user: dict = Depends(get_current_user)):
    """GET /api/tenants/{id}/stats"""
    users = await fetch_one("SELECT COUNT(*) AS c FROM users WHERE tenant_id = %s AND is_active = 1", [tenant_id])
    products = await fetch_one("SELECT COUNT(*) AS c FROM products WHERE tenant_id = %s", [tenant_id])
    sales = await fetch_one(
        "SELECT COUNT(*) AS c, COALESCE(SUM(total_amount), 0) AS total FROM product_sales WHERE tenant_id = %s",
        [tenant_id]
    )
    return {
        "employee_count": users["c"] if users else 0,
        "product_count": products["c"] if products else 0,
        "sale_count": sales["c"] if sales else 0,
        "total_revenue": float(sales["total"]) if sales else 0,
    }


@router.post("")
async def create_tenant(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/tenants"""
    tid = await execute(
        "INSERT INTO tenants (name, owner_name, owner_email, owner_phone, business_type, address, city, is_active, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 1, NOW())",
        [body.get("name"), body.get("owner_name"), body.get("owner_email"),
         body.get("owner_phone"), body.get("business_type", "restaurant"),
         body.get("address"), body.get("city")],
    )
    return {"id": tid, "message": "Tenant created"}


@router.put("/{tenant_id}")
async def update_tenant(tenant_id: int, body: dict = Body(...), user: dict = Depends(get_current_user)):
    """PUT /api/tenants/{id}"""
    fields, params = [], []
    for key in ("name", "owner_name", "owner_email", "owner_phone", "business_type", "address", "city", "is_active"):
        if key in body:
            fields.append(f"{key} = %s")
            params.append(body[key])
    if fields:
        params.append(tenant_id)
        await execute(f"UPDATE tenants SET {', '.join(fields)}, updated_at = NOW() WHERE id = %s", params)
    return {"message": "Tenant updated"}


@router.post("/{tenant_id}/toggle")
async def toggle_status(tenant_id: int, user: dict = Depends(get_current_user)):
    """POST /api/tenants/{id}/toggle"""
    tenant = await fetch_one("SELECT is_active FROM tenants WHERE id = %s", [tenant_id])
    if tenant:
        new_status = 0 if tenant["is_active"] else 1
        await execute("UPDATE tenants SET is_active = %s, updated_at = NOW() WHERE id = %s", [new_status, tenant_id])
        return {"is_active": new_status}
    return {"error": "Tenant not found"}


# ── Visibility / Hierarchy ──

@router.get("/users/visible")
async def get_visible_users(viewer_id: int = Query(...), user: dict = Depends(get_current_user)):
    """GET /api/tenants/users/visible?viewer_id=..."""
    viewer = await fetch_one("SELECT id, role, tenant_id FROM users WHERE id = %s", [viewer_id])
    if not viewer:
        return {"user_ids": []}

    role = viewer.get("role", "")
    if role == "master_admin":
        rows = await fetch_all("SELECT id FROM users")
    elif role == "admin":
        rows = await fetch_all("SELECT id FROM users WHERE tenant_id = %s", [viewer["tenant_id"]])
    elif role == "manager":
        rows = await fetch_all("SELECT id FROM users WHERE manager_id = %s", [viewer_id])
        rows.append({"id": viewer_id})
    else:
        rows = [{"id": viewer_id}]

    return {"user_ids": [r["id"] for r in rows]}


@router.get("/users/subordinates")
async def get_subordinates(manager_id: int = Query(...), user: dict = Depends(get_current_user)):
    """GET /api/tenants/users/subordinates?manager_id=..."""
    rows = await fetch_all("SELECT id, name, username, role FROM users WHERE manager_id = %s AND is_active = 1", [manager_id])
    return {"subordinates": rows}


@router.put("/users/{uid}/manager")
async def assign_manager(uid: int, body: dict = Body(...), user: dict = Depends(get_current_user)):
    """PUT /api/tenants/users/{id}/manager"""
    await execute("UPDATE users SET manager_id = %s WHERE id = %s", [body["manager_id"], uid])
    return {"message": "Manager assigned"}


@router.post("/{tenant_id}/admin")
async def create_tenant_admin(tenant_id: int, body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/tenants/{id}/admin"""
    pw_hash = hash_password(body["password"])
    uid = await execute(
        "INSERT INTO users (name, username, password, role, tenant_id, is_active) VALUES (%s, %s, %s, 'admin', %s, 1)",
        [body["name"], body["username"], pw_hash, tenant_id],
    )
    return {"id": uid, "message": "Tenant admin created"}
