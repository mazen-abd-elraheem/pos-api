"""
POS API — Configuration
Loads settings from .env using pydantic-settings pattern (manual for zero deps).
"""

import os
from dotenv import load_dotenv

# Load .env from project root directory
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(env_path)


import json

def _load_jwt_secret() -> str:
    val = os.getenv("JWT_SECRET")
    if val and val != "change-this-secret-key":
        return val
    try:
        # Check Pos/security_config.json
        sec_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "security_config.json")
        if os.path.exists(sec_path):
            with open(sec_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d.get("jwt_secret"):
                    return d["jwt_secret"]
    except Exception:
        pass
    return "ZB5v0es1pPSUd3QMA6un9hoo0_02hCTCdY35xnKvg9QgrmxTgLNh7jN4hLckXcRdmeqhiwLVI5JBdJtXMEvmZg"


class Settings:
    """Application settings read from environment variables."""

    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DB_HOST: str = os.getenv("DB_HOST", "pos-server-system.mysql.database.azure.com")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_NAME: str = os.getenv("DB_NAME", "pos-system")
    DB_USER: str = os.getenv("DB_USER", "adminmazen")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "012m@Mazen")
    DB_SSL: bool = os.getenv("DB_SSL", "false").lower() == "true"

    JWT_SECRET: str = _load_jwt_secret()
    JWT_EXPIRY: int = int(os.getenv("JWT_EXPIRY", "86400"))

    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "*")
    APP_DEBUG: bool = os.getenv("APP_DEBUG", "false").lower() == "true"
    APP_ENV: str = os.getenv("APP_ENV", "production")


settings = Settings()
