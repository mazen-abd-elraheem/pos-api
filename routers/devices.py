"""
Devices Router — /api/devices
Device registration, audit logging, and sales summary.
"""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Query, Body
from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


@router.get("")
async def get_all_devices(user: dict = Depends(get_current_user)):
    """GET /api/devices"""
    rows = await fetch_all("SELECT * FROM devices ORDER BY last_seen DESC")
    for r in rows:
        for k in ("registered_at", "last_seen"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].isoformat()
    return {"devices": rows}


@router.post("")
async def register_device(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/devices — register or update a device."""
    name = body.get("device_name", "unknown")
    location = body.get("location", "")
    device_id = body.get("device_id") or str(uuid.uuid4())

    existing = await fetch_one("SELECT id FROM devices WHERE device_id = %s", [device_id])
    if existing:
        await execute("UPDATE devices SET last_seen = NOW() WHERE device_id = %s", [device_id])
        return {"device_id": device_id, "message": "Device updated"}
    else:
        await execute(
            "INSERT INTO devices (device_id, device_name, location, registered_at, last_seen) VALUES (%s, %s, %s, NOW(), NOW())",
            [device_id, name, location],
        )
        return {"device_id": device_id, "message": "Device registered"}


@router.put("/{device_id}/seen")
async def update_last_seen(device_id: str, user: dict = Depends(get_current_user)):
    """PUT /api/devices/{id}/seen — heartbeat."""
    await execute("UPDATE devices SET last_seen = NOW() WHERE device_id = %s", [device_id])
    return {"message": "Updated"}


@router.put("/{device_id}")
async def update_device(device_id: int, body: dict = Body(...), user: dict = Depends(get_current_user)):
    """PUT /api/devices/{id} — update device fields (e.g. toggle is_active)."""
    fields, params = [], []
    for key in ("device_name", "location", "is_active"):
        if key in body:
            fields.append(f"{key} = %s")
            params.append(body[key])
    if not fields:
        return {"message": "No fields to update"}
    params.append(device_id)
    await execute(f"UPDATE devices SET {', '.join(fields)} WHERE id = %s", params)
    return {"message": "Device updated"}


# ── Audit Logs ──

@router.get("/audit")
async def get_audit_logs(
    limit: int = Query(100),
    user_id: int = Query(None),
    action: str = Query(None),
    user: dict = Depends(get_current_user),
):
    """GET /api/devices/audit"""
    sql = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if user_id:
        sql += " AND user_id = %s"
        params.append(user_id)
    if action:
        sql += " AND action = %s"
        params.append(action)
    sql += " ORDER BY timestamp DESC LIMIT %s"
    params.append(limit)
    rows = await fetch_all(sql, params)
    for r in rows:
        if isinstance(r.get("timestamp"), datetime):
            r["timestamp"] = r["timestamp"].isoformat()
    return {"logs": rows}


@router.post("/audit")
async def log_audit(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """POST /api/devices/audit"""
    await execute(
        "INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details, device_id, success, timestamp) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
        [body.get("user_id"), body.get("action"), body.get("resource_type"),
         body.get("resource_id"), body.get("details"), body.get("device_id"),
         body.get("success", 1)],
    )
    return {"message": "Audit logged"}


# ── Device Sales Summary ──

@router.get("/sales-summary")
async def device_sales_summary(user: dict = Depends(get_current_user)):
    """GET /api/devices/sales-summary"""
    rows = await fetch_all(
        "SELECT d.device_id, d.device_name, d.location, "
        "COALESCE(COUNT(ds.id), 0) AS total_sales, "
        "COALESCE(SUM(ds.total_amount), 0) AS total_amount "
        "FROM devices d LEFT JOIN device_sales ds ON d.id = ds.device_id "
        "GROUP BY d.id ORDER BY total_amount DESC"
    )
    return {"summary": rows}
