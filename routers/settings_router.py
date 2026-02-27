"""
Settings Router — /api/settings
Mirrors PHP SettingsController.php
"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from database import fetch_all, fetch_one, execute_transaction
from auth import get_current_user

router = APIRouter()


@router.get("")
async def index(user_data: dict = Depends(get_current_user)):
    """GET /api/settings — all app_config + store_settings."""
    settings: dict = {}

    # app_config key-value pairs
    try:
        configs = await fetch_all("SELECT config_key, config_value FROM app_config")
        for c in configs:
            settings[c["config_key"]] = c["config_value"]
    except Exception:
        pass

    # store_settings row
    try:
        store = await fetch_one("SELECT * FROM store_settings LIMIT 1")
        if store:
            settings["store"] = store
    except Exception:
        pass

    return {"settings": settings}


@router.put("")
async def update(body: dict, user_data: dict = Depends(get_current_user)):
    """PUT /api/settings — upsert key-value pairs (admin only)."""
    if user_data.get("role") not in ("admin", "master_admin"):
        return JSONResponse(
            {"error": True, "message": "Admin access required"}, status_code=403
        )

    queries = []
    for key, value in body.items():
        val = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        queries.append((
            "INSERT INTO app_config (config_key, config_value, updated_at) "
            "VALUES (%s, %s, NOW()) "
            "ON DUPLICATE KEY UPDATE config_value = VALUES(config_value), updated_at = NOW()",
            [key, val],
        ))

    try:
        await execute_transaction(queries)
        return {"message": "Settings updated"}
    except Exception as e:
        return JSONResponse(
            {"error": True, "message": f"Failed to update settings: {str(e)}"},
            status_code=500,
        )
