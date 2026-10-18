"""
pos-api-fastapi/services/license_service.py — Tamper-Proof License & Edition Manager
Ported from infra/license_manager.py and infra/edition_config.py
"""

import hashlib
import hmac
import os
import struct
import socket
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from core.database import fetch_one, execute, engine

logger = logging.getLogger("license_service")

# Secret key for HMAC-SHA256 signature
_SECRET_KEY = b"SkyPDV_License_2026_JP_Invest_Secret_Key_X9k2m"

EDITIONS = {
    "trial": {
        "tier": 0,
        "label": "Trial Edition",
        "max_devices": 3,
        "features": ["lan_connect", "local_db"],
    },
    "basic": {
        "tier": 1,
        "label": "Basic (LAN)",
        "max_devices": 5,
        "features": ["lan_connect", "local_db"],
    },
    "pro": {
        "tier": 2,
        "label": "Pro (Remote)",
        "max_devices": 15,
        "features": ["lan_connect", "local_db", "remote_access", "gist_registry"],
    },
    "enterprise": {
        "tier": 3,
        "label": "Enterprise (Cloud)",
        "max_devices": 999,
        "features": ["lan_connect", "local_db", "remote_access", "gist_registry", "cloud_sync"],
    },
}


def get_device_uuid() -> str:
    """Generate or retrieve persistent machine identifier."""
    uuid_file = "/tmp/.device_uuid" if os.name != "nt" else os.path.join(os.path.dirname(__file__), "..", ".device_uuid")
    try:
        if os.path.exists(uuid_file):
            with open(uuid_file, "r") as f:
                return f.read().strip()
    except Exception:
        pass

    import uuid
    device_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()))
    try:
        with open(uuid_file, "w") as f:
            f.write(device_uuid)
    except Exception:
        pass
    return device_uuid


def generate_license_key(days: int, plan: str = "basic") -> str:
    """Generate an HMAC-signed license key string like 'SKYP-XXXX-XXXX-...'."""
    plan_codes = {"trial": "T", "basic": "B", "pro": "P", "enterprise": "E"}
    plan_code = plan_codes.get(plan.lower(), "B")

    ts = int(datetime.now().timestamp())
    payload = struct.pack(">cHI", plan_code.encode(), days, ts)
    signature = hmac.new(_SECRET_KEY, payload, hashlib.sha256).digest()[:6]

    raw = payload + signature
    hex_str = raw.hex().upper()
    parts = [hex_str[i : i + 4] for i in range(0, len(hex_str), 4)]
    return "SKYP-" + "-".join(parts)


def validate_license_key(key: str) -> Dict[str, Any]:
    """Validate signature and extract plan, days, and created_at."""
    try:
        clean = key.upper().replace("SKYP-", "").replace("-", "").replace(" ", "")
        raw = bytes.fromhex(clean)
        if len(raw) < 13:
            return {"valid": False, "error": f"Key too short ({len(raw)} bytes, expected 13)"}

        payload = raw[:7]
        sig_in_key = raw[7:13]

        expected_sig = hmac.new(_SECRET_KEY, payload, hashlib.sha256).digest()[:6]
        if not hmac.compare_digest(sig_in_key, expected_sig):
            return {"valid": False, "error": "Invalid cryptographic signature"}

        plan_code_bytes, days, ts = struct.unpack(">cHI", payload)
        plan_code = plan_code_bytes.decode()

        plan_map = {"T": "trial", "B": "basic", "P": "pro", "E": "enterprise"}
        plan = plan_map.get(plan_code, "basic")

        return {
            "valid": True,
            "plan": plan,
            "days": days,
            "created_ts": ts,
            "created_at": datetime.fromtimestamp(ts).isoformat(),
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


async def ensure_license_schema():
    """Ensure license_history table exists in database across MySQL and PostgreSQL."""
    try:
        dialect_name = getattr(engine.dialect, "name", "mysql")
        if dialect_name == "postgresql":
            await execute("""
            CREATE TABLE IF NOT EXISTS license_history (
                id SERIAL PRIMARY KEY,
                license_key VARCHAR(100) NOT NULL UNIQUE,
                plan VARCHAR(50) NOT NULL,
                days INT NOT NULL,
                device_uuid VARCHAR(100) NOT NULL,
                activated_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
            """)
        else:
            await execute("""
            CREATE TABLE IF NOT EXISTS license_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                license_key VARCHAR(100) NOT NULL UNIQUE,
                plan VARCHAR(50) NOT NULL,
                days INT NOT NULL,
                device_uuid VARCHAR(100) NOT NULL,
                activated_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                INDEX idx_key (license_key),
                INDEX idx_device (device_uuid)
            )
            """)
    except Exception as e:
        logger.warning(f"ensure_license_schema: {e}")


async def _upsert_app_config(key: str, value: str):
    """Safely insert or update key in app_config table without relying on unique constraint."""
    try:
        row = await fetch_one("SELECT id FROM app_config WHERE config_key = %s LIMIT 1", [key])
        if row:
            await execute("UPDATE app_config SET config_value = %s WHERE id = %s", [value, row["id"]])
        else:
            await execute("INSERT INTO app_config (config_key, config_value) VALUES (%s, %s)", [key, value])
    except Exception as e:
        logger.warning(f"Failed to upsert app_config {key}: {e}")


async def activate_license(key: str, tenant_id: Optional[int] = None) -> Dict[str, Any]:
    """Validate and activate license key with anti-reuse, hardware binding, and single-use checks."""
    info = validate_license_key(key)
    if not info.get("valid"):
        return {"success": False, "message": info.get("error", "Invalid key")}

    plan = info["plan"]
    days = info["days"]
    created_ts = info.get("created_ts", 0)
    now = datetime.now()

    # 1. Anti-Age check: key must be activated within 365 days of generation
    if created_ts > 0 and (int(now.timestamp()) - created_ts) > (365 * 86400):
        return {"success": False, "message": "This license key has expired (activation window exceeded)."}

    # 2. Anti-Reuse & Hardware Lock Verification
    await ensure_license_schema()
    current_device = get_device_uuid()

    try:
        existing_record = await fetch_one(
            "SELECT id, device_uuid, activated_at, expires_at FROM license_history WHERE license_key = %s",
            [key]
        )
        if existing_record:
            if existing_record.get("device_uuid") and existing_record["device_uuid"] != current_device:
                return {
                    "success": False,
                    "message": f"This license key is locked to another terminal hardware ID ({existing_record['device_uuid'][:8]}...).",
                }
            return {
                "success": False,
                "message": "This license key has already been activated and cannot be reused.",
            }
    except Exception as e:
        logger.warning(f"License history check: {e}")

    # 3. Single-Use Trial Check
    if plan == "trial":
        trial_row = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'trial_used' LIMIT 1")
        if trial_row and trial_row.get("config_value") == "1":
            return {
                "success": False,
                "message": "The 14-day free trial has already been used on this installation. Please enter a valid commercial license key.",
            }
        await _upsert_app_config("trial_used", "1")
        await _upsert_app_config("trial_started_at", now.strftime("%Y-%m-%d %H:%M:%S"))

    end_date = now + timedelta(days=days)

    # 4. Store in app_config
    await _upsert_app_config("active_license_key", key)
    await _upsert_app_config("license_plan", plan)
    await _upsert_app_config("license_end_date", end_date.strftime("%Y-%m-%d %H:%M:%S"))
    await _upsert_app_config("last_clock_timestamp", now.strftime("%Y-%m-%d %H:%M:%S"))

    # 5. Record in license_history table to permanently consume the key
    try:
        await execute(
            "INSERT INTO license_history (license_key, plan, days, device_uuid, activated_at, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [key, plan, days, current_device, now.strftime("%Y-%m-%d %H:%M:%S"), end_date.strftime("%Y-%m-%d %H:%M:%S")],
        )
    except Exception as e:
        logger.warning(f"Failed to record in license_history: {e}")

    # 6. Update tenant if tenant_id provided or first tenant exists
    try:
        if tenant_id:
            await execute(
                "UPDATE tenants SET plan = %s, subscription_start = %s, subscription_end = %s, is_active = 1 WHERE id = %s",
                [plan, now, end_date, tenant_id],
            )
        else:
            first_t = await fetch_one("SELECT id FROM tenants ORDER BY id ASC LIMIT 1")
            if first_t:
                await execute(
                    "UPDATE tenants SET plan = %s, subscription_start = %s, subscription_end = %s, is_active = 1 WHERE id = %s",
                    [plan, now, end_date, first_t["id"]],
                )
    except Exception as e:
        logger.warning(f"Tenant license update: {e}")

    edition_info = EDITIONS.get(plan, EDITIONS["basic"])

    return {
        "success": True,
        "message": f"License activated for {plan.title()} edition ({days} days)",
        "plan": plan,
        "edition_label": edition_info["label"],
        "max_devices": edition_info["max_devices"],
        "features": edition_info["features"],
        "expires_at": end_date.isoformat(),
        "days_remaining": days,
        "device_uuid": current_device,
    }


async def get_license_status(tenant_id: Optional[int] = None) -> Dict[str, Any]:
    """Retrieve current license details, days remaining, anti-tampering check, and edition limits."""
    tenant = None
    try:
        if tenant_id:
            tenant = await fetch_one("SELECT * FROM tenants WHERE id = %s", [tenant_id])
        if not tenant:
            tenant = await fetch_one("SELECT * FROM tenants ORDER BY id ASC LIMIT 1")
    except Exception:
        tenant = None

    plan = tenant.get("plan") if tenant else None
    sub_end = tenant.get("subscription_end") if tenant else None

    # Fallback to app_config
    if not plan:
        plan_conf = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'license_plan' LIMIT 1")
        if plan_conf and plan_conf.get("config_value"):
            plan = plan_conf["config_value"]

    if not sub_end:
        end_conf = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'license_end_date' LIMIT 1")
        if end_conf and end_conf.get("config_value"):
            try:
                sub_end = datetime.strptime(end_conf["config_value"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

    key_conf = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'active_license_key' LIMIT 1")
    active_key = key_conf.get("config_value") if key_conf else None

    # Check trial state
    trial_row = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'trial_used' LIMIT 1")
    trial_used = (trial_row.get("config_value") == "1") if trial_row else False

    now = datetime.now()
    days_left = 0
    is_active = False
    clock_tampered = False

    # Anti-Clock Tampering Check
    try:
        last_clock_row = await fetch_one("SELECT config_value FROM app_config WHERE config_key = 'last_clock_timestamp' LIMIT 1")
        if last_clock_row and last_clock_row.get("config_value"):
            last_clock = datetime.strptime(last_clock_row["config_value"], "%Y-%m-%d %H:%M:%S")
            # If current time is earlier than last recorded timestamp by more than 1 hour -> Tampering!
            if now < (last_clock - timedelta(hours=1)):
                clock_tampered = True
                logger.warning(f"Clock tampering detected: now={now} < last_clock={last_clock}")
        
        if not clock_tampered:
            await _upsert_app_config("last_clock_timestamp", now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        logger.warning(f"Clock check: {e}")

    if sub_end and not clock_tampered:
        if isinstance(sub_end, datetime):
            delta = sub_end - now
            days_left = max(0, delta.days)
            is_active = sub_end > now
        elif isinstance(sub_end, str):
            try:
                dt = datetime.fromisoformat(sub_end)
                days_left = max(0, (dt - now).days)
                is_active = dt > now
            except Exception:
                pass

    resolved_plan = (plan or "unlicensed").lower()
    edition = EDITIONS.get(resolved_plan, {
        "tier": 0,
        "label": "Unlicensed",
        "max_devices": 1,
        "features": [],
    })

    # Current registered devices count
    current_devices = 0
    try:
        dev_count = await fetch_one("SELECT COUNT(*) as c FROM devices WHERE is_active = 1")
        current_devices = dev_count["c"] if dev_count else 0
    except Exception:
        current_devices = 0

    return {
        "is_active": is_active,
        "is_licensed": is_active and bool(sub_end) and not clock_tampered,
        "plan": resolved_plan,
        "edition_label": edition["label"],
        "max_devices": edition["max_devices"],
        "current_devices": current_devices,
        "device_limit_reached": current_devices >= edition["max_devices"],
        "features": edition["features"],
        "expires_at": sub_end.isoformat() if isinstance(sub_end, datetime) else str(sub_end or ""),
        "days_remaining": days_left,
        "device_uuid": get_device_uuid(),
        "active_key": active_key,
        "trial_used": trial_used,
        "clock_tampered": clock_tampered,
        "tamper_warning": "System clock manipulation detected. Please restore the correct system time." if clock_tampered else None,
    }

