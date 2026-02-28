"""
Config Router — /api/config
Application configuration CRUD (app_config table).
"""
from fastapi import APIRouter, Depends, Query, Body
from database import fetch_all, fetch_one, execute
from auth import get_current_user

router = APIRouter()


@router.get("")
async def get_config(
    key: str = Query(...),
    tenant_id: int = Query(None),
    user: dict = Depends(get_current_user),
):
    """GET /api/config?key=...&tenant_id=..."""
    if tenant_id is not None:
        row = await fetch_one(
            "SELECT config_value, config_type FROM app_config WHERE config_key = %s AND tenant_id = %s",
            [key, tenant_id],
        )
    else:
        row = await fetch_one(
            "SELECT config_value, config_type FROM app_config WHERE config_key = %s AND tenant_id IS NULL",
            [key],
        )
    if not row:
        return {"value": None}
    return {"value": row["config_value"], "type": row.get("config_type", "string")}


@router.get("/all")
async def get_all_config(user: dict = Depends(get_current_user)):
    """GET /api/config/all — preload all configs."""
    rows = await fetch_all("SELECT config_key, config_value, config_type, tenant_id FROM app_config")
    return {"configs": rows}


@router.put("")
async def set_config(body: dict = Body(...), user: dict = Depends(get_current_user)):
    """PUT /api/config — upsert a config value."""
    key = body["key"]
    value = str(body["value"])
    category = body.get("category", "general")
    config_type = body.get("config_type", "string")
    tenant_id = body.get("tenant_id")
    description = body.get("description")

    if tenant_id is not None:
        existing = await fetch_one(
            "SELECT id FROM app_config WHERE config_key = %s AND tenant_id = %s", [key, tenant_id]
        )
    else:
        existing = await fetch_one(
            "SELECT id FROM app_config WHERE config_key = %s AND tenant_id IS NULL", [key]
        )

    if existing:
        await execute(
            "UPDATE app_config SET config_value = %s, config_type = %s, category = %s WHERE id = %s",
            [value, config_type, category, existing["id"]],
        )
    else:
        await execute(
            "INSERT INTO app_config (tenant_id, config_key, config_value, config_type, category, description) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [tenant_id, key, value, config_type, category, description],
        )
    return {"message": "Config saved"}
