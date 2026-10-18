"""
services/voice/config.py — API key resolution for Gemini and Groq.

Resolution order: DB config → environment variable → ai_config.json fallback.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def resolve_gemini_key() -> str | None:
    """DB → env → legacy JSON."""
    try:
        from controller import get_config
        key = get_config("gemini_api_key")
        if key:
            return key
    except Exception:
        pass

    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key

    try:
        p = Path(__file__).parent.parent.parent / "ai_config.json"
        if p.exists():
            return json.loads(p.read_text()).get("gemini_api_key")
    except Exception:
        pass
    return None


def resolve_groq_key() -> str | None:
    """Resolve Groq API key: DB → env → ai_config.json."""
    try:
        from controller import get_config
        key = get_config("groq_api_key")
        if key:
            return key
    except Exception:
        pass

    key = os.getenv("GROQ_API_KEY")
    if key:
        return key

    try:
        p = Path(__file__).parent.parent.parent / "ai_config.json"
        if p.exists():
            data = json.loads(p.read_text())
            key = data.get("groq_api_key")
            if key:
                logger.info("Groq API key loaded from ai_config.json")
                return key
    except Exception as e:
        logger.warning(f"Failed to load Groq key: {e}")
    return None
