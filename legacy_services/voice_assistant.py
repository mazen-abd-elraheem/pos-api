"""
services/voice_assistant.py — Backward-compatible shim.

All logic has been refactored into the services.voice package:
  - services/voice/config.py   — API key resolution
  - services/voice/tools.py    — POS tool functions + dispatch
  - services/voice/schemas.py  — Gemini function-calling schemas
  - services/voice/prompt.py   — System prompt template
  - services/voice/live.py     — LiveSession + LiveVoiceManager
  - services/voice/engine.py   — VoiceAssistantEngine
  - services/voice/audio.py    — Audio playback utilities

This file re-exports everything so existing imports continue to work:
    import services.voice_assistant as _va
    from services.voice_assistant import VoiceAssistantEngine
"""
# Re-export the entire public API from the voice package
from services.voice import *                     # noqa: F401,F403

# Also re-export the callback globals so they can be SET by the page
# (from services.voice import * only imports the initial None values)
import services.voice.tools as _tools            # noqa: F401
