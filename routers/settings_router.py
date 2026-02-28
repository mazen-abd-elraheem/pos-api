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


# ─── Discounts ───────────────────────────────────────────────────────────

@router.get("/discounts")
async def get_discounts(user_data: dict = Depends(get_current_user)):
    """GET /api/settings/discounts — all active discounts."""
    rows = await fetch_all("SELECT * FROM discounts WHERE active = 1")
    return {"discounts": rows}


@router.post("/discounts")
async def create_discount(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/settings/discounts"""
    from database import execute
    await execute(
        "INSERT INTO discounts (name, discount_type, value, applicable_to, product_id, category, end_date, active) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 1)",
        [body.get("name"), body.get("discount_type"), body.get("value"),
         body.get("applicable_to", "all"), body.get("product_id"),
         body.get("category"), body.get("end_date")],
    )
    return {"message": "Discount created"}


@router.delete("/discounts/{discount_id}")
async def delete_discount(discount_id: int, user_data: dict = Depends(get_current_user)):
    """DELETE /api/settings/discounts/{id}"""
    from database import execute
    await execute("DELETE FROM discounts WHERE id = %s", [discount_id])
    return {"message": "Discount deleted"}


# ─── Translations ────────────────────────────────────────────────────────

@router.get("/translations")
async def get_translations(user_data: dict = Depends(get_current_user)):
    """GET /api/settings/translations"""
    rows = await fetch_all("SELECT `key`, english, arabic FROM translations")
    trans = {}
    for r in rows:
        trans[r["key"]] = {"english": r.get("english", ""), "arabic": r.get("arabic", "")}
    return {"translations": trans}


@router.post("/translations")
async def create_translation(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/settings/translations"""
    from database import execute
    await execute(
        "INSERT INTO translations (`key`, english, arabic) VALUES (%s, %s, %s)",
        [body.get("key"), body.get("english", ""), body.get("arabic", "")],
    )
    return {"message": "Translation created"}

