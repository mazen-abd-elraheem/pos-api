"""
Settings Router — /api/settings
Mirrors PHP SettingsController.php
"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from typing import Optional
from core.database import fetch_all, fetch_one, execute_transaction
from auth.security import get_current_user, get_optional_user

router = APIRouter()


@router.get("")
async def index(user_data: Optional[dict] = Depends(get_optional_user)):
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


@router.get("/store")
async def get_store_settings(user_data: Optional[dict] = Depends(get_optional_user)):
    """GET /api/settings/store — fetch store config for receipts/taxes."""
    from core.database import fetch_one
    try:
        store = await fetch_one("SELECT * FROM store_settings LIMIT 1")
        if not store:
            return {}
        return store
    except Exception as e:
        return JSONResponse({"error": True, "message": str(e)}, status_code=500)


@router.post("/store")
async def update_store_settings(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/settings/store — update store config."""
    from core.database import execute
    if user_data.get("role") not in ("admin", "master_admin"):
        return JSONResponse({"error": True, "message": "Admin access required"}, status_code=403)

    try:
        # check if exists
        from core.database import fetch_one
        store = await fetch_one("SELECT id FROM store_settings LIMIT 1")
        if store:
            await execute(
                """
                UPDATE store_settings SET 
                store_name = %s, phone = %s, address = %s, vat_percentage = %s, 
                vat_number = %s, header_text = %s, footer_text = %s, business_type = %s,
                updated_at = NOW()
                WHERE id = %s
                """,
                [
                    body.get("store_name", ""),
                    body.get("phone", ""),
                    body.get("address", ""),
                    body.get("vat_percentage", 15.0),
                    body.get("vat_number", ""),
                    body.get("header_text", ""),
                    body.get("footer_text", ""),
                    body.get("business_type", "restaurant"),
                    store["id"]
                ]
            )
        else:
            await execute(
                """
                INSERT INTO store_settings (
                    store_name, phone, address, vat_percentage, vat_number, header_text, footer_text, business_type
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    body.get("store_name", ""),
                    body.get("phone", ""),
                    body.get("address", ""),
                    body.get("vat_percentage", 15.0),
                    body.get("vat_number", ""),
                    body.get("header_text", ""),
                    body.get("footer_text", ""),
                    body.get("business_type", "restaurant")
                ]
            )
        return {"message": "Store settings updated successfully"}
    except Exception as e:
        return JSONResponse({"error": True, "message": str(e)}, status_code=500)



# ─── Discounts ───────────────────────────────────────────────────────────

@router.get("/discounts")
async def get_discounts(user_data: dict = Depends(get_current_user)):
    """GET /api/settings/discounts — all active discounts."""
    rows = await fetch_all("SELECT * FROM discounts WHERE active = 1")
    return {"discounts": rows}


@router.post("/discounts")
async def create_discount(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/settings/discounts"""
    from core.database import execute
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
    from core.database import execute
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
    from core.database import execute
    await execute(
        "INSERT INTO translations (`key`, english, arabic) VALUES (%s, %s, %s)",
        [body.get("key"), body.get("english", ""), body.get("arabic", "")],
    )
    return {"message": "Translation created"}


# ─── WhatsApp Settings ───────────────────────────────────────────────────

@router.get("/whatsapp")
async def get_whatsapp_settings(user_data: Optional[dict] = Depends(get_optional_user)):
    """GET /api/settings/whatsapp"""
    try:
        row = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'whatsapp_config'")
        if row and row.get("config_value"):
            return json.loads(row["config_value"])
        return {"enabled": False, "api_url": "", "api_key": "", "instance_id": ""}
    except Exception:
        return {"enabled": False, "api_url": "", "api_key": "", "instance_id": ""}


@router.post("/whatsapp")
async def save_whatsapp_settings(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/settings/whatsapp"""
    from core.database import execute
    try:
        val = json.dumps(body)
        await execute(
            "INSERT INTO app_config (config_key, config_value, updated_at) "
            "VALUES ('whatsapp_config', %s, NOW()) "
            "ON DUPLICATE KEY UPDATE config_value = VALUES(config_value), updated_at = NOW()",
            [val]
        )
        return {"message": "WhatsApp settings saved"}
    except Exception as e:
        return JSONResponse({"error": True, "message": str(e)}, status_code=500)


@router.post("/whatsapp/test")
async def test_whatsapp(body: dict, user_data: dict = Depends(get_current_user)):
    """POST /api/settings/whatsapp/test"""
    return {"message": "Test message queued successfully"}


