"""
POS API — Configuration
Loads settings from .env using pydantic-settings pattern (manual for zero deps).
"""

import os
from dotenv import load_dotenv

# Load .env from this directory
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


class Settings:
    """Application settings read from environment variables."""

    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_NAME: str = os.getenv("DB_NAME", "u611315500_pos")
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_SSL: bool = os.getenv("DB_SSL", "false").lower() == "true"

    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-this-secret-key")
    JWT_EXPIRY: int = int(os.getenv("JWT_EXPIRY", "86400"))

    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "*")
    APP_DEBUG: bool = os.getenv("APP_DEBUG", "false").lower() == "true"
    APP_ENV: str = os.getenv("APP_ENV", "production")


settings = Settings()
