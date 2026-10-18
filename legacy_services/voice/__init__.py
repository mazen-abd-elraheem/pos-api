"""
services/voice/ — Organized voice assistant package.

This __init__.py re-exports the public API so that existing code using
`from services.voice_assistant import X` (via the shim) continues to work.
"""
from .config import resolve_gemini_key, resolve_groq_key
from .tools import (
    TOOL_DISPATCH, TOOL_PERMISSIONS,
    _nav_callback, _add_to_cart_callback, _view_cart_callback,
    _clear_cart_callback, _checkout_callback,
)
from .schemas import build_tool_declarations
from .prompt import SYSTEM_PROMPT_TEMPLATE, GROQ_DIALECT_LOCK, TTS_SYSTEM_PROMPT, build_system_prompt
from .live import LiveSession, LiveVoiceManager
from .engine import VoiceAssistantEngine
from .audio import _play_wav_bytes, _play_wav_file

# Backward-compatible aliases (old names used by pages/voice_assistant.py)
_resolve_gemini_key = resolve_gemini_key
_resolve_groq_key = resolve_groq_key
_build_tool_declarations = build_tool_declarations
SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE

__all__ = [
    # Config
    "resolve_gemini_key", "resolve_groq_key",
    "_resolve_gemini_key", "_resolve_groq_key",  # backward compat
    # Tools
    "TOOL_DISPATCH", "TOOL_PERMISSIONS",
    # Schemas
    "build_tool_declarations", "_build_tool_declarations",
    # Prompt
    "SYSTEM_PROMPT_TEMPLATE", "SYSTEM_PROMPT", "GROQ_DIALECT_LOCK",
    "TTS_SYSTEM_PROMPT", "build_system_prompt",
    # Live
    "LiveSession", "LiveVoiceManager",
    # Engine
    "VoiceAssistantEngine",
    # Audio
    "_play_wav_bytes", "_play_wav_file",
]
