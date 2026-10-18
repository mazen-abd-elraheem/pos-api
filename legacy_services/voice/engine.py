"""
services/voice/engine.py — VoiceAssistantEngine: LLM orchestration for POS voice commands.

Fallback chain: Groq (fast cloud) → Ollama (local) → Gemini (Google AI).
STT: Google Speech Recognition (primary) → Groq Whisper (fallback).
TTS: Gemini Live API native audio.

Note: The old method name `_vosk_transcribe` was misleading — it never used Vosk.
      It's been renamed to `_transcribe_audio` which accurately describes its function:
      Google Speech Recognition (primary) → Groq Whisper (fallback).
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import resolve_gemini_key, resolve_groq_key
from .tools import TOOL_DISPATCH, TOOL_PERMISSIONS
from .schemas import build_tool_declarations
from .prompt import SYSTEM_PROMPT_TEMPLATE, GROQ_DIALECT_LOCK, TTS_SYSTEM_PROMPT, build_system_prompt
from .live import LiveSession

logger = logging.getLogger(__name__)


class VoiceAssistantEngine:
    """Voice assistant with Ollama (primary, unlimited) + Gemini (fallback) for POS ops."""

    OLLAMA_URL = "http://localhost:11434"
    OLLAMA_MODEL = "phi3:mini"

    def __init__(self, api_key: str | None = None, user_id: int | None = None):
        self._api_key = api_key or resolve_gemini_key()
        self._groq_key = resolve_groq_key()
        self._user_id = user_id
        self._model = None
        self._chat = None
        self._history: list[dict] = []
        self._initialized = False
        self._allowed_tools: set[str] = set()
        self._ollama_ok = False
        self._ollama_messages: list[dict] = []
        self._groq_ok = bool(self._groq_key)
        self._groq_messages: list[dict] = []
        # Persistent TTS LiveSession — never cold-start mid-conversation
        self._live_session: LiveSession | None = None
        self._live_session_lock = threading.Lock()
        self._current_tts_player = None  # set by caller before generate_speech
        self._tts_muted = False
        logger.info(f"Engine init: groq_key={bool(self._groq_key)}, groq_ok={self._groq_ok}, api_key={bool(self._api_key)}")

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key) or self._ollama_ok or self._groq_ok

    @property
    def has_table_access(self) -> bool:
        """Check if the current user has table permissions."""
        return "list_tables" in self._allowed_tools

    def _get_allowed_tools(self) -> set[str]:
        """Filter tools based on user permissions."""
        allowed = set()
        try:
            from controller.roles import check_permission
            for tool_name, perm_name in TOOL_PERMISSIONS.items():
                if self._user_id is None or check_permission(self._user_id, perm_name):
                    allowed.add(tool_name)
        except Exception:
            # Fallback: allow all tools if permission check fails
            allowed = set(TOOL_DISPATCH.keys())
        return allowed

    # Model fallback chain — if one quota is exhausted, try the next
    _MODEL_CHAIN = [

        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]

    def _build_system_prompt(self) -> str:
        """Build the dynamic system prompt based on current DB products."""
        categories_str = "General items"
        sample_str = "Various products"
        try:
            from controller.products import get_products
            products = get_products()
            if products:
                cats = set()
                samples = []
                for p in products:
                    c = p.category if hasattr(p, 'category') else p.get('category', '')
                    if c: cats.add(c)
                
                for p in products:
                    t = p.title if hasattr(p, 'title') else p.get('title', '')
                    pr = float(p.price if hasattr(p, 'price') else p.get('price', 0))
                    if t: samples.append(f"{t} ({pr} EGP)")
                
                if cats: categories_str = ", ".join(list(cats)[:10])
                if samples: sample_str = ", ".join(samples)
        except Exception as e:
            logger.error(f"Error building dynamic context: {e}")

        return SYSTEM_PROMPT_TEMPLATE.format(
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            categories=categories_str,
            sample_products=sample_str,
        )

    def _check_ollama(self) -> bool:
        """Check if Ollama is running locally."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.OLLAMA_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read())
                    models = [m.get("name", "") for m in data.get("models", [])]
                    # Check if our target model (or any model) is available
                    self._ollama_ok = any(
                        self.OLLAMA_MODEL.split(":")[0] in m for m in models
                    ) or len(models) > 0
                    if self._ollama_ok:
                        logger.info(f"Ollama available with models: {models}")
                    return self._ollama_ok
        except Exception:
            pass
        self._ollama_ok = False
        return False

    def _build_ollama_tools(self) -> list:
        """Build OpenAI-compatible tool list for Ollama."""
        tools = []
        for decl in build_tool_declarations():
            if decl["name"] not in self._allowed_tools:
                continue
            tool = {
                "type": "function",
                "function": {
                    "name": decl["name"],
                    "description": decl.get("description", ""),
                    "parameters": decl.get("parameters", {"type": "object", "properties": {}}),
                }
            }
            tools.append(tool)
        return tools

    def process_text_ollama(self, user_text: str) -> str:
        """Process text via local Ollama (unlimited, no quota)."""
        import urllib.request

        # Init system message on first call
        if not self._ollama_messages:
            self._ollama_messages = [
                {"role": "system", "content": self._build_system_prompt()}
            ]

        self._ollama_messages.append({"role": "user", "content": user_text})
        logger.info(f"Ollama processing: {user_text[:60]}...")

        # Build request
        tools = self._build_ollama_tools()
        payload = {
            "model": self.OLLAMA_MODEL,
            "messages": self._ollama_messages[-20:],  # Keep last 20 messages
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        max_rounds = 5
        for round_i in range(max_rounds):
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.OLLAMA_URL}/api/chat",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.loads(resp.read())

            msg = result.get("message", {})
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            if not tool_calls:
                # Final text response
                self._ollama_messages.append({"role": "assistant", "content": content})
                self._history.append({"role": "user", "text": user_text, "time": datetime.now().strftime("%H:%M")})
                self._history.append({"role": "assistant", "text": content, "time": datetime.now().strftime("%H:%M")})
                logger.info(f"Ollama response: {content[:80]}...")
                return content

            # Execute tool calls
            self._ollama_messages.append(msg)  # Add assistant's tool_call message
            for tc in tool_calls:
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                fn_args = fn.get("arguments", {})
                if isinstance(fn_args, str):
                    fn_args = json.loads(fn_args)

                logger.info(f"Ollama tool call: {fn_name}({fn_args})")
                tool_fn = TOOL_DISPATCH.get(fn_name)
                if tool_fn:
                    try:
                        tool_result = tool_fn(**fn_args)
                    except Exception as e:
                        tool_result = {"success": False, "error": str(e)}
                else:
                    tool_result = {"success": False, "error": f"Unknown tool: {fn_name}"}

                self._ollama_messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_result, ensure_ascii=False, default=str),
                })

            # Update payload for next round
            payload["messages"] = self._ollama_messages[-20:]

        return content or "I processed your request."

    def process_text_groq(self, user_text: str) -> str:
        """Process text via Groq (ultra-fast cloud, 14400 RPD free)."""
        from groq import Groq

        client = Groq(api_key=self._groq_key)

        if not self._groq_messages:
            sys_prompt = self._build_system_prompt()
            # Groq/Llama-specific: strong dialect lock + prevent function syntax leak
            sys_prompt += (
                "\n\n=== CRITICAL OUTPUT RULES (Groq/Llama) ===\n"
                "1. LANGUAGE LOCK: Every single word you write MUST be عامية مصرية (Egyptian Arabic). "
                "NEVER output ANY word in English, French, Russian, Turkish, or any other language. "
                "If the user speaks English, you STILL reply in عامية مصرية only.\n"
                "2. FORBIDDEN WORDS: Never use فصحى words like: لقد، إنّ، لديّ، يمكنك، بالتأكيد، بالطبع، حسناً، إذن، هل تريد، أود أن، تم بنجاح.\n"
                "3. REQUIRED STYLE: Use ONLY these Egyptian words: عايز/عايزة، عندنا، إيه، دلوقتي، كده، لقيت، تمام، أيوه، مفيش، يا فندم، يا باشا، حاضر.\n"
                "4. TOOL CALLS: Use the API's tool_calls mechanism. NEVER write <function=...> tags in your text.\n"
                "5. Keep responses SHORT — 1-3 sentences max. Your text will be spoken aloud.\n"
                "6. NEVER mix scripts or alphabets. Output Arabic script ONLY.\n"
            )
            self._groq_messages = [
                {"role": "system", "content": sys_prompt}
            ]

        self._groq_messages.append({"role": "user", "content": user_text})
        logger.info(f"Groq processing: {user_text[:60]}...")

        tools = self._build_ollama_tools()  # Same OpenAI-compatible format

        max_rounds = 5
        for _ in range(max_rounds):
            kwargs = {
                "model": "llama-3.3-70b-versatile",
                "messages": self._groq_messages[-20:],
                "temperature": 0.7,
                "max_tokens": 1024,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            try:
                response = client.chat.completions.create(**kwargs)
            except Exception as e:
                error_str = str(e)
                # Extract failed_generation text from 400 errors
                if "failed_generation" in error_str:
                    import re
                    match = re.search(r"'failed_generation':\s*'([^']*)'", error_str)
                    if match:
                        content = match.group(1)
                        # Clean LLM artifacts
                        content = re.sub(r'<function=[^<]*</function>', '', content, flags=re.DOTALL)
                        content = re.sub(r'<\|[^|]*\|>', '', content)
                        content = content.strip(': \n\t')
                        if content:
                            self._groq_messages.append({"role": "assistant", "content": content})
                            logger.info(f"Groq recovered from failed tool call: {content[:80]}")
                            return content
                raise
            msg = response.choices[0].message

            if not msg.tool_calls:
                content = msg.content or ""
                # Clean ALL LLM artifacts from response
                import re
                # ── Strip thinking/reasoning blocks ──
                # Pattern: **Bold Header**\n\nReasoning paragraph...
                # These are internal chain-of-thought leaks from the model
                content = re.sub(
                    r'\*\*[^*]+\*\*\s*\n+(?:[^\n]*(?:I\'m |I\'ve |I will |My approach|The plan|This approach|I\'ll )[^\n]*\n*)+',
                    '', content, flags=re.IGNORECASE
                )
                # Also strip lines that are pure reasoning indicators
                content = re.sub(r'^(?:I\'m (?:now |starting|deciding|revising)|My approach|The plan is)[^\n]*\n?', '', content, flags=re.MULTILINE | re.IGNORECASE)
                # Function call syntax
                content = re.sub(r'<function=\w+[^>]*>.*?</function>', '', content, flags=re.DOTALL)
                content = re.sub(r'<function=[^<]*</function>', '', content, flags=re.DOTALL)
                # Llama special tokens & HTML role tags
                content = re.sub(r'<\|[^|]*\|>', '', content)  # <|end_header_id|> etc
                content = re.sub(r'<a\s+href="assistant[^"]*">[^<]*</a>:\s*', '', content)
                content = re.sub(r'</?[a-z]+[^>]*>', '', content)  # stray HTML tags
                # Clean up excessive whitespace from removals
                content = re.sub(r'\n{3,}', '\n\n', content)
                content = content.strip(': \n\t')
                self._groq_messages.append({"role": "assistant", "content": content})
                self._history.append({"role": "user", "text": user_text, "time": datetime.now().strftime("%H:%M")})
                self._history.append({"role": "assistant", "text": content, "time": datetime.now().strftime("%H:%M")})
                logger.info(f"Groq response ({response.usage.total_tokens} tokens): {content[:80]}...")
                return content

            # Execute tool calls — build clean message (whitelist only)
            clean_tool_calls = []
            for tc in msg.tool_calls:
                clean_tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    }
                })
            self._groq_messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": clean_tool_calls,
            })

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                logger.info(f"Groq tool call: {fn_name}({fn_args})")

                tool_fn = TOOL_DISPATCH.get(fn_name)
                if tool_fn:
                    try:
                        tool_result = tool_fn(**fn_args)
                    except Exception as e:
                        tool_result = {"success": False, "error": str(e)}
                else:
                    tool_result = {"success": False, "error": f"Unknown tool: {fn_name}"}

                self._groq_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, ensure_ascii=False, default=str),
                })

        return msg.content or "I processed your request."

    def initialize(self, model_index: int = 0) -> bool:
        """Initialize: Groq (fast cloud) → Ollama (local) → Gemini (fallback)."""
        # Always resolve tools
        self._allowed_tools = self._get_allowed_tools()
        all_tools = build_tool_declarations()
        filtered_tools = [t for t in all_tools if t["name"] in self._allowed_tools]
        logger.info(f"Voice assistant: {len(filtered_tools)}/{len(all_tools)} tools enabled for user {self._user_id}")

        # 1. Try Groq first (ultra-fast, 14400 RPD)
        if self._groq_ok:
            logger.info("Voice assistant using Groq (llama-3.3-70b) — fast, 14400 RPD")
            self._initialized = True
            return True

        # 2. Try Ollama (unlimited local, but slow on CPU)
        if self._check_ollama():
            logger.info(f"Voice assistant using Ollama ({self.OLLAMA_MODEL}) — unlimited")
            self._initialized = True
            return True

        # Fallback to Gemini
        if not self._api_key:
            logger.warning("No Gemini API key and Ollama not available")
            return False
        try:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)

            model_name = self._MODEL_CHAIN[min(model_index, len(self._MODEL_CHAIN) - 1)]
            model_kwargs = {
                "model_name": model_name,
                "system_instruction": self._build_system_prompt(),
            }
            if filtered_tools:
                model_kwargs["tools"] = [{"function_declarations": filtered_tools}]

            self._model = genai.GenerativeModel(**model_kwargs)
            self._chat = self._model.start_chat(history=[])
            self._initialized = True
            self._current_model_index = model_index
            logger.info(f"Voice assistant initialized with Gemini: {model_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize voice assistant: {e}")
            self._initialized = False
            return False

    def _switch_to_next_model(self) -> bool:
        """Try to switch to the next model in the fallback chain."""
        next_idx = getattr(self, '_current_model_index', 0) + 1
        if next_idx < len(self._MODEL_CHAIN):
            logger.info(f"Switching to fallback model: {self._MODEL_CHAIN[next_idx]}")
            self._initialized = False
            return self.initialize(model_index=next_idx)
        return False

    def shutdown(self):
        """Release all resources — disconnect persistent TTS session, clear state."""
        logger.info("VoiceAssistantEngine shutting down")
        with self._live_session_lock:
            if self._live_session:
                try:
                    self._live_session.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting TTS session: {e}")
                self._live_session = None
        self._current_tts_player = None
        self._initialized = False
        self._chat = None
        self._model = None
        self._history.clear()
        self._ollama_messages.clear()
        self._groq_messages.clear()

    def process_text(self, user_text: str, **kw) -> dict:
        """Unified API: text in → {text, audio, error} out."""
        on_text_fragment = kw.get("on_text_fragment")
        try:
            text = self._process_text_str(user_text)
            if on_text_fragment and text:
                on_text_fragment(text)
            return {"text": text, "audio": b"", "error": None}
        except Exception as e:
            return {"text": "", "audio": b"", "error": str(e)}

    def _process_text_str(self, user_text: str) -> str:
        """Process text: Groq (fast) → Ollama (local) → Gemini (fallback).

        Handles function calls automatically — executes the tool,
        sends the result back, and returns the final text response.
        """
        if not self._initialized:
            if not self.initialize():
                return "Voice assistant not configured. Please add API key in settings."

        # ── 1. Gemini (best Arabic, reliable tools, free tier) ──
        if self._api_key and not self._chat:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self._api_key)
                all_tools = build_tool_declarations()
                filtered_tools = [t for t in all_tools if t["name"] in self._allowed_tools]
                model_kwargs = {
                    "model_name": self._MODEL_CHAIN[0],
                    "system_instruction": self._build_system_prompt(),
                }
                if filtered_tools:
                    model_kwargs["tools"] = [{"function_declarations": filtered_tools}]
                self._model = genai.GenerativeModel(**model_kwargs)
                self._chat = self._model.start_chat(history=[])
                logger.info(f"Gemini primary initialized: {self._MODEL_CHAIN[0]}")
            except Exception as e:
                logger.warning(f"Gemini init failed: {e}, trying Groq...")

        # ── 2. Groq fallback (only if Gemini not available) ──
        if not self._chat and self._groq_ok:
            try:
                return self.process_text_groq(user_text)
            except Exception as e:
                logger.warning(f"Groq failed: {e}, trying Ollama...")

        # ── 3. Ollama fallback (only if Gemini not available) ──
        if not self._chat and self._ollama_ok:
            try:
                return self.process_text_ollama(user_text)
            except Exception as e:
                logger.warning(f"Ollama failed: {e}")

        # ── Gemini fallback ──
        if not self._chat:
            # Ollama was primary, Gemini not initialized yet
            if not self._api_key:
                return "Ollama is not responding and no Gemini API key configured."
            try:
                import google.generativeai as genai
                genai.configure(api_key=self._api_key)
                all_tools = build_tool_declarations()
                filtered_tools = [t for t in all_tools if t["name"] in self._allowed_tools]
                model_kwargs = {
                    "model_name": self._MODEL_CHAIN[0],
                    "system_instruction": self._build_system_prompt(),
                }
                if filtered_tools:
                    model_kwargs["tools"] = [{"function_declarations": filtered_tools}]
                self._model = genai.GenerativeModel(**model_kwargs)
                self._chat = self._model.start_chat(history=[])
                logger.info(f"Gemini fallback initialized: {self._MODEL_CHAIN[0]}")
            except Exception as e:
                return f"Both Ollama and Gemini unavailable: {e}"

        import time as _time

        max_retries = 3
        for attempt in range(max_retries):
            try:
                import json
                import google.generativeai as genai

                logger.info(f"Voice assistant processing (Gemini): {user_text[:80]}")
                response = self._chat.send_message(
                    user_text,
                    request_options={"timeout": 30},
                )

                # Handle function calls (may be multiple rounds)
                max_rounds = 5
                round_count = 0
                while response.candidates and round_count < max_rounds:
                    candidate = response.candidates[0]
                    parts = candidate.content.parts

                    # Check if any part is a function call
                    function_calls = [p for p in parts if hasattr(p, 'function_call') and p.function_call.name]
                    if not function_calls:
                        break  # No function calls — we have the final text

                    # Execute each function call
                    function_responses = []
                    for fc_part in function_calls:
                        fc = fc_part.function_call
                        fn_name = fc.name
                        fn_args = dict(fc.args) if fc.args else {}

                        logger.info(f"Voice assistant calling: {fn_name}({fn_args})")

                        # Execute the tool
                        tool_fn = TOOL_DISPATCH.get(fn_name)
                        if tool_fn:
                            try:
                                result = tool_fn(**fn_args)
                            except Exception as e:
                                logger.error(f"Tool {fn_name} error: {e}")
                                result = {"success": False, "error": str(e)}
                        else:
                            result = {"success": False, "error": f"Unknown tool: {fn_name}"}

                        # Convert result to JSON string for safe serialization
                        result_str = json.dumps(result, ensure_ascii=False, default=str)

                        function_responses.append(
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=fn_name,
                                    response={"result": result_str},
                                )
                            )
                        )

                    # Send function results back to Gemini
                    response = self._chat.send_message(
                        genai.protos.Content(parts=function_responses),
                        request_options={"timeout": 30},
                    )
                    round_count += 1

                # Extract final text response
                text = ""
                if response.candidates:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, 'text') and part.text:
                            text += part.text

                if not text:
                    text = "I processed your request."

                # Store in history
                self._history.append({
                    "role": "user",
                    "text": user_text,
                    "time": datetime.now().strftime("%H:%M"),
                })
                self._history.append({
                    "role": "assistant",
                    "text": text,
                    "time": datetime.now().strftime("%H:%M"),
                })

                return text

            except Exception as e:
                error_str = str(e)
                error_lower = error_str.lower()

                logger.error(f"Voice assistant error (attempt {attempt+1}): {e}")

                # Rate limit (429) — only match REAL rate limit errors
                is_rate_limit = (
                    "429" in error_str
                    or "quota" in error_lower
                    or "rate limit" in error_lower
                    or "rate_limit" in error_lower
                    or "resource_exhausted" in error_lower
                    or "resourceexhausted" in error_lower
                )

                if is_rate_limit:
                    # Extract retry delay from error message
                    import re as _re
                    delay_match = _re.search(r'retry in (\d+)', error_lower)
                    wait_secs = int(delay_match.group(1)) + 2 if delay_match else 30
                    wait_secs = min(wait_secs, 60)
                    
                    if attempt < max_retries - 1:
                        logger.info(f"Rate limited — auto-retrying in {wait_secs}s...")
                        _time.sleep(wait_secs)
                        # Re-init on same model after waiting
                        self.initialize()
                        continue

                    return (
                        "API quota temporarily exceeded. Please wait ~30 seconds and try again.\n"
                        "Your quota resets automatically."
                    )

                # Other errors — retry once
                if attempt < max_retries - 1:
                    _time.sleep(2)
                    continue
                return f"Sorry, I encountered an error: {error_str[:200]}"

        return "Sorry, all retries failed. Please try again later."

    def _groq_transcribe(self, audio_path: str) -> str | None:
        """Ultra-fast STT via Groq Whisper (whisper-large-v3-turbo, ~0.3s)."""
        if not self._groq_key:
            return None
        try:
            from groq import Groq
            client = Groq(api_key=self._groq_key)
            with open(audio_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=("audio.wav", f),
                    model="whisper-large-v3-turbo",
                    language="ar",
                    response_format="text",
                )
            text = transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
            if not text:
                return None

            # ── Hallucination filter ──
            # Whisper hallucinates full sentences when audio is unclear
            hallucination_patterns = [
                "ترجمة", "الرقم", "نانسي", "الدولي", "تطابق",
                "Thank you", "Didn't", "Subtitles", "Subscribe",
                "أعجبني", "اشترك", "شكرا لمشاهدتكم",
            ]
            text_lower = text.lower()
            for pattern in hallucination_patterns:
                if pattern.lower() in text_lower:
                    logger.warning(f"Groq Whisper: rejected hallucination: '{text}'")
                    return None

            # Reject if too many words for a short recording (likely hallucination)
            word_count = len(text.split())
            if word_count > 15:
                logger.warning(f"Groq Whisper: rejected long hallucination ({word_count} words): '{text[:60]}'")
                return None

            logger.info(f"Groq Whisper STT: '{text}'")
            return text
        except Exception as e:
            logger.warning(f"Groq Whisper STT failed: {e}")
            return None

    def _transcribe_audio(self, audio_path: str) -> str | None:
        """Transcribe audio: Google free STT (accurate) → Groq Whisper (fallback)."""
        # ── Audio quality pre-check ──
        try:
            import wave as _wave
            with _wave.open(audio_path, "rb") as wf:
                n_frames = wf.getnframes()
                rate = wf.getframerate()
                duration = n_frames / rate if rate else 0
            if duration < 0.5:
                logger.warning(f"STT: audio too short ({duration:.1f}s), skipping")
                return None
            if duration > 30:
                logger.warning(f"STT: audio too long ({duration:.1f}s), skipping")
                return None
        except Exception:
            pass

        # ── Primary: Google free STT (accurate for Arabic) ──
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            # Tune for noisy environments
            recognizer.energy_threshold = 300
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = 0.8

            with sr.AudioFile(audio_path) as source:
                # Adjust for ambient noise from first 0.3s
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio_data = recognizer.record(source)

            # Try Arabic first
            try:
                text = recognizer.recognize_google(audio_data, language="ar-EG")
                if text and text.strip():
                    logger.info(f"STT Google (ar): {text}")
                    return text.strip()
            except sr.UnknownValueError:
                logger.info("STT Google (ar): could not understand audio")

            # Try English
            try:
                text = recognizer.recognize_google(audio_data, language="en-US")
                if text and text.strip():
                    logger.info(f"STT Google (en): {text}")
                    return text.strip()
            except sr.UnknownValueError:
                logger.info("STT Google (en): could not understand audio")
        except Exception as e:
            logger.warning(f"Google STT failed: {e}")

        # ── Fallback: Groq Whisper (~0.3s) ──
        result = self._groq_transcribe(audio_path)
        if result:
            return result

        logger.warning("STT: Could not understand audio")
        return None


    def process_audio_native(self, audio_path: str, on_audio_chunk=None) -> dict:
        """Native Audio Dialog via Gemini Live API (WebSocket).
        
        Uses gemini-2.5-flash-native-audio-preview — separate quota from gemini-2.5-flash.
        Audio in (16kHz PCM) → Live API → Audio out (24kHz PCM) + text.
        
        Args:
            on_audio_chunk: Optional callback(bytes) called with each PCM chunk
                           as it arrives from the WebSocket for real-time playback.
        
        Returns dict with:
          - 'text': str (response text)
          - 'audio_path': str | None (path to WAV response)  
          - 'transcription': str | None
        """
        import asyncio
        
        async def _run_live_session():
            from google import genai
            from google.genai import types
            import wave
            import struct
            
            api_key = self._api_key or resolve_gemini_key()
            if not api_key:
                return {"text": "No API key configured.", "audio_path": None, "transcription": None}
            
            client = genai.Client(api_key=api_key)
            
            # ── Convert WAV to raw PCM 16kHz mono ──
            with wave.open(audio_path, 'rb') as wf:
                src_rate = wf.getframerate()
                src_channels = wf.getnchannels()
                src_width = wf.getsampwidth()
                raw_frames = wf.readframes(wf.getnframes())
            
            # Convert to mono if stereo
            if src_channels == 2:
                samples = struct.unpack(f'<{len(raw_frames)//2}h', raw_frames)
                mono = [(samples[i] + samples[i+1]) // 2 for i in range(0, len(samples), 2)]
                raw_frames = struct.pack(f'<{len(mono)}h', *mono)
            
            # Simple resample to 16kHz if needed
            if src_rate != 16000:
                samples = struct.unpack(f'<{len(raw_frames)//2}h', raw_frames)
                ratio = src_rate / 16000
                resampled = [samples[min(int(i * ratio), len(samples)-1)] 
                             for i in range(int(len(samples) / ratio))]
                raw_frames = struct.pack(f'<{len(resampled)}h', *resampled)
            
            pcm_input = raw_frames
            
            # ── Build tool declarations for Live API ──
            all_tools = build_tool_declarations()
            filtered_tools = [t for t in all_tools if t["name"] in self._allowed_tools] if self._allowed_tools else all_tools
            
            # ── Live API config with function calling ──
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                tools=[{"function_declarations": filtered_tools}] if filtered_tools else None,
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Enceladus",
                        )
                    )
                ),
                system_instruction=self._build_system_prompt(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
            )
            
            result = {"text": None, "audio_path": None, "transcription": None}
            audio_chunks = []
            
            # ── Connect and exchange audio ──
            async with client.aio.live.connect(
                model="gemini-2.5-flash-native-audio-latest",
                config=config,
            ) as session:
                
                # Send audio in chunks (8KB each)
                CHUNK = 8192
                for i in range(0, len(pcm_input), CHUNK):
                    chunk = pcm_input[i:i+CHUNK]
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=chunk,
                            mime_type="audio/pcm;rate=16000",
                        )
                    )
                
                # Signal end of user audio turn
                await session.send_realtime_input(audio_stream_end=True)
                
                # Receive response with timeout + handle tool calls
                text_parts = []
                try:
                    async def _collect():
                        async for msg in session.receive():
                            # ── Handle tool/function calls from the model ──
                            if msg.tool_call:
                                function_responses = []
                                for fc in msg.tool_call.function_calls:
                                    fn_name = fc.name
                                    fn_args = dict(fc.args) if fc.args else {}
                                    logger.info(f"Live API tool call: {fn_name}({fn_args})")
                                    
                                    tool_fn = TOOL_DISPATCH.get(fn_name)
                                    if tool_fn:
                                        try:
                                            tool_result = tool_fn(**fn_args)
                                        except Exception as e:
                                            tool_result = {"success": False, "error": str(e)}
                                    else:
                                        tool_result = {"success": False, "error": f"Unknown tool: {fn_name}"}
                                    
                                    function_responses.append(
                                        types.FunctionResponse(
                                            id=fc.id,
                                            name=fn_name,
                                            response={"result": json.dumps(tool_result, ensure_ascii=False, default=str)},
                                        )
                                    )
                                
                                # Send tool results back to the model
                                await session.send_tool_response(function_responses=function_responses)
                                continue  # Continue receiving the model's voice response
                            
                            if msg.server_content:
                                sc = msg.server_content
                                if sc.model_turn:
                                    for part in sc.model_turn.parts:
                                        if part.inline_data and part.inline_data.data:
                                            audio_chunks.append(part.inline_data.data)
                                            if on_audio_chunk:
                                                try:
                                                    on_audio_chunk(part.inline_data.data)
                                                except Exception:
                                                    pass
                                        if part.text:
                                            text_parts.append(part.text)
                                            logger.info(f"Live text part: {part.text[:80]}")
                                # Capture audio transcription (what the model spoke)
                                if hasattr(sc, 'output_audio_transcription') and sc.output_audio_transcription:
                                    oat = sc.output_audio_transcription
                                    if hasattr(oat, 'text') and oat.text:
                                        text_parts.append(oat.text)
                                        logger.info(f"Live transcription: {oat.text[:80]}")
                                    elif isinstance(oat, str) and oat:
                                        text_parts.append(oat)
                                        logger.info(f"Live transcription (str): {oat[:80]}")
                                if sc.turn_complete:
                                    break
                    
                    await asyncio.wait_for(_collect(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning("Live API receive timed out after 30s")
            
            # ── Save audio response as WAV ──
            if audio_chunks:
                pcm_out = b"".join(audio_chunks)
                wav_path = os.path.join(
                    tempfile.gettempdir(),
                    f"pos_native_audio_{int(_time.time()*1000)}.wav"
                )
                with wave.open(wav_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(pcm_out)
                result["audio_path"] = wav_path
            
            # ── Collect text ──
            if text_parts:
                full_text = " ".join(text_parts).strip()
                # Clean thinking/reasoning blocks from response
                full_text = re.sub(
                    r'\*\*[^*]+\*\*\s*\n+(?:[^\n]*(?:I\'m |I\'ve |I will |My approach|The plan|This approach|I\'ll |I am |Okay, I|The user)[^\n]*\n*)+',
                    '', full_text, flags=re.IGNORECASE
                )
                full_text = re.sub(r'^(?:I\'m (?:now |starting|deciding|revising|thinking|focusing|envisioning)|My approach|The plan is|Okay, I\'m|The user wants)[^\n]*\n?', '', full_text, flags=re.MULTILINE | re.IGNORECASE)
                full_text = re.sub(r'\*\*[^*]+\*\*\s*', '', full_text)  # stray bold headers
                full_text = re.sub(r'\n{3,}', '\n\n', full_text)
                full_text = full_text.strip(': \n\t')
                result["text"] = full_text
            
            # If we got audio but no text, set a default
            if result["audio_path"] and not result["text"]:
                result["text"] = "[Voice response]"
            
            # Update history
            if result["text"]:
                self._history.append({
                    "role": "user",
                    "text": "[Voice]",
                    "time": datetime.now().strftime("%H:%M"),
                })
                self._history.append({
                    "role": "assistant",
                    "text": result["text"],
                    "time": datetime.now().strftime("%H:%M"),
                })
            
            logger.info(f"Live API native audio: text={bool(result['text'])}, audio={bool(result['audio_path'])}")
            return result
        
        # Run the async Live API session
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(_run_live_session())
            finally:
                # Properly shutdown async generators
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            return result
        except Exception as e:
            logger.warning(f"Native audio dialog (Live API) failed: {e}")
            return {"text": None, "audio_path": None, "transcription": None, "error": str(e)}

    def process_audio_file(self, audio_path: str) -> str:
        """Process audio: STT + Groq/Ollama (fast) or Gemini (fallback)."""
        if not self._initialized:
            if not self.initialize():
                return "Voice assistant not configured."

        # ── 1. Groq path: Google STT → Groq chat (instant) ──
        if self._groq_ok:
            transcription = self._transcribe_audio(audio_path)
            if not transcription:
                return "Could not understand the audio. Please try again."
            try:
                response = self.process_text_groq(transcription)
                return f"TRANSCRIPTION: {transcription}\n{response}"
            except Exception as e:
                logger.warning(f"Groq audio path failed: {e}")
                return f"TRANSCRIPTION: {transcription}\nSorry, I had a processing error. Please try again."

        # ── 2. Ollama path: Google STT → Ollama chat ──
        if self._ollama_ok:
            try:
                transcription = self._transcribe_audio(audio_path)
                if transcription:
                    response = self.process_text_ollama(transcription)
                    return f"TRANSCRIPTION: {transcription}\n{response}"
                else:
                    return "Could not understand the audio. Please try again."
            except Exception as e:
                logger.warning(f"Ollama audio path failed: {e}")

        try:
            import google.generativeai as genai

            # Init Gemini if not done (Ollama was primary)
            if not self._chat:
                if not self._api_key:
                    return "Ollama failed and no Gemini API key configured."
                genai.configure(api_key=self._api_key)
                all_tools = build_tool_declarations()
                filtered_tools = [t for t in all_tools if t["name"] in self._allowed_tools]
                model_kwargs = {
                    "model_name": self._MODEL_CHAIN[0],
                    "system_instruction": self._build_system_prompt(),
                }
                if filtered_tools:
                    model_kwargs["tools"] = [{"function_declarations": filtered_tools}]
                self._model = genai.GenerativeModel(**model_kwargs)
                self._chat = self._model.start_chat(history=[])
                logger.info(f"Gemini fallback initialized for audio: {self._MODEL_CHAIN[0]}")

            # Read audio file as inline bytes (much faster than upload_file)
            with open(audio_path, 'rb') as f:
                audio_bytes = f.read()

            audio_part = {
                "inline_data": {
                    "mime_type": "audio/wav",
                    "data": audio_bytes,
                }
            }

            # Send audio to chat with instruction to transcribe + respond
            response = self._chat.send_message(
                [
                    "The user sent a voice message. You MUST:\n"
                    "1. First line: write ONLY the transcription prefixed with TRANSCRIPTION: \n"
                    "2. Second line onward: your response (do NOT repeat what they said)\n\n"
                    "Example format:\n"
                    "TRANSCRIPTION: افتح طاولة 3\n"
                    "تم فتح طاولة 3\n\n"
                    "If they're giving a POS command, execute the relevant function. "
                    "Respond in Egyptian Arabic dialect. Be brief and natural.",
                    audio_part,
                ],
                request_options={"timeout": 30},
            )

            # Handle function calls same as text
            max_rounds = 5
            round_count = 0
            while response.candidates and round_count < max_rounds:
                candidate = response.candidates[0]
                parts = candidate.content.parts
                function_calls = [p for p in parts if hasattr(p, 'function_call') and p.function_call.name]
                if not function_calls:
                    break

                function_responses = []
                for fc_part in function_calls:
                    fc = fc_part.function_call
                    fn_name = fc.name
                    fn_args = dict(fc.args) if fc.args else {}
                    logger.info(f"Voice (audio) calling: {fn_name}({fn_args})")

                    tool_fn = TOOL_DISPATCH.get(fn_name)
                    if tool_fn:
                        try:
                            result = tool_fn(**fn_args)
                        except Exception as e:
                            result = {"success": False, "error": str(e)}
                    else:
                        result = {"success": False, "error": f"Unknown tool: {fn_name}"}

                    function_responses.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=fn_name,
                                response={"result": result},
                            )
                        )
                    )

                response = self._chat.send_message(
                    genai.protos.Content(parts=function_responses)
                )
                round_count += 1

            text = ""
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        text += part.text

            if not text:
                text = "I processed your voice command."

            self._history.append({
                "role": "user",
                "text": "[Voice message]",
                "time": datetime.now().strftime("%H:%M"),
            })
            self._history.append({
                "role": "assistant",
                "text": text,
                "time": datetime.now().strftime("%H:%M"),
            })

            return text

        except Exception as e:
            error_str = str(e)
            error_lower = error_str.lower()
            
            import traceback
            logger.error(f"Audio processing error: {e}")
            
            # Only match REAL rate limit errors
            is_rate_limit = (
                "429" in error_str
                or "quota" in error_lower
                or "rate limit" in error_lower
                or "rate_limit" in error_lower
                or "resource_exhausted" in error_lower
                or "resourceexhausted" in error_lower
            )
            
            if is_rate_limit:
                # Extract retry delay from error message
                import re as _re
                delay_match = _re.search(r'retry in (\d+)', error_lower)
                wait_secs = int(delay_match.group(1)) + 2 if delay_match else 30
                
                # Cap wait to 60 seconds max
                wait_secs = min(wait_secs, 60)
                
                logger.info(f"Rate limited — auto-retrying in {wait_secs}s on same model...")
                _time.sleep(wait_secs)
                
                # Re-initialize and retry ONCE on the same model (don't switch)
                try:
                    self.initialize()
                    
                    with open(audio_path, 'rb') as f:
                        audio_bytes = f.read()
                    
                    audio_part = {
                        "inline_data": {
                            "mime_type": "audio/wav",
                            "data": audio_bytes,
                        }
                    }
                    
                    response = self._chat.send_message(
                        [
                            "The user sent a voice message. You MUST:\n"
                            "1. First line: write ONLY the transcription prefixed with TRANSCRIPTION: \n"
                            "2. Second line onward: your response (do NOT repeat what they said)\n\n"
                            "Respond in Egyptian Arabic dialect. Be brief and natural.",
                            audio_part,
                        ],
                    )
                    
                    text = ""
                    if response.candidates:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, 'text') and part.text:
                                text += part.text
                    
                    return text or "I processed your voice command."
                    
                except Exception as retry_err:
                    logger.error(f"Retry also failed: {retry_err}")
                    return (
                        "API quota temporarily exceeded. Please wait ~30 seconds and try again.\n"
                        "Your quota resets automatically."
                    )
            
            # Show the REAL error so we can debug
            return f"Error: {error_str[:300]}"

    def get_history(self) -> list[dict]:
        return list(self._history)

    def clear_history(self):
        self._history.clear()
        if self._model:
            try:
                self._chat = self._model.start_chat(history=[])
            except Exception:
                pass

    def reset(self):
        """Full reset — re-initialize on next call."""
        self._initialized = False
        self._chat = None
        self._history.clear()

    def shutdown(self):
        """Shutdown engine — disconnect persistent TTS session + reset."""
        if self._live_session:
            try:
                self._live_session.disconnect()
            except Exception:
                pass
            self._live_session = None
        self.reset()

    def process_wav(self, wav_path: str, **kw) -> dict:
        """
        Unified voice API: WAV → STT → Groq → {text, transcription, audio, error}.
        Flow: Google STT (free, fast) → Groq text+tools (fast) → return text.
        Gemini is NOT used here — it's only for TTS via generate_speech().
        """
        # ── 1. Transcribe user audio via Google STT ──
        user_said = ""
        try:
            user_said = self._transcribe_audio(wav_path) or ""
        except Exception as e:
            logger.warning(f"STT failed: {e}")

        if not user_said:
            return {
                "text": "🤔 لم أستطع فهم ما قلته — حاول تاني.",
                "transcription": "",
                "audio": b"",
                "error": "STT failed",
            }

        logger.info(f"STT heard: '{user_said}'")

        # ── 2. Process text via Groq (fast, with tool calling) ──
        try:
            response_text = self._process_text_str(user_said)
            logger.info(f"Voice response: '{response_text[:80]}'")
            return {
                "text": response_text,
                "transcription": user_said,
                "audio": b"",  # UI calls generate_speech() separately for TTS
                "error": None,
            }
        except Exception as e:
            logger.error(f"Text processing failed: {e}")
            return {
                "text": f"❌ حصل مشكلة: {str(e)[:100]}",
                "transcription": user_said,
                "audio": b"",
                "error": str(e),
            }

    # ── Persistent TTS LiveSession management ────────────────────────────────

    def _build_tts_system_prompt(self) -> str:
        """System prompt that locks the TTS voice into Egyptian dialect."""
        return """أنت كاشير مصري بتتكلم بعامية مصرية صرفة.
لما حد يبعتلك نص، قوله بصوتك الطبيعي زي ما بتتكلم في الشارع بالظبط.
ممنوع تقرأ بالفصحى. ممنوع تغير الكلام. قوله بالظبط كما هو بس بلهجة مصرية.
خليك سريع وطبيعي زي الكاشير الحقيقي."""

    def _get_or_create_live_session(self) -> LiveSession | None:
        """Return existing TTS session or create one. Verifies connection."""
        with self._live_session_lock:
            if self._live_session and self._live_session.connected:
                return self._live_session

            # Clean up old broken session
            if self._live_session:
                try:
                    self._live_session.disconnect()
                except Exception:
                    pass
                self._live_session = None

            api_key = self._api_key or resolve_gemini_key()
            if not api_key:
                logger.error("No API key for TTS LiveSession")
                return None

            logger.info("Creating persistent TTS LiveSession...")
            session = LiveSession(
                api_key=api_key,
                system_prompt=self._build_tts_system_prompt(),
                tool_declarations=[],
                allowed_tools=set(),
            )

            session.on_audio_out    = self._on_tts_audio
            session.on_disconnected = self._on_live_disconnected
            session.on_error        = lambda e: logger.error(f"TTS LiveSession error: {e}")
            session.on_turn_done    = self._on_tts_turn_done

            session.connect()

            # Wait for actual connection (up to 5s)
            deadline = _time.time() + 5.0
            while _time.time() < deadline:
                if session.connected:
                    self._live_session = session
                    logger.info("Persistent TTS LiveSession verified connected")
                    return session
                _time.sleep(0.1)

            logger.warning("TTS LiveSession failed to connect within 5s")
            try:
                session.disconnect()
            except Exception:
                pass
            return None

    def _on_live_disconnected(self):
        """Auto-reconnect if TTS session drops."""
        logger.warning("TTS LiveSession dropped — will reconnect on next turn")
        self._live_session = None

    def _on_tts_audio(self, pcm_bytes: bytes):
        """Called for each audio chunk from LiveSession — feed directly to player."""
        if self._current_tts_player and not self._tts_muted:
            self._current_tts_player.feed(pcm_bytes)

    def _on_tts_turn_done(self):
        """Called when the TTS model finishes speaking — signal player to drain."""
        if self._current_tts_player:
            self._current_tts_player.done()

    def _generate_speech_coldstart(self, text: str, player=None) -> bytes:
        """Reliable cold-start TTS: opens a fresh WebSocket, collects all audio, feeds player."""
        import asyncio

        api_key = self._api_key or resolve_gemini_key()
        if not api_key:
            logger.error("No API key for cold-start TTS")
            return b""

        collected_pcm = []

        async def _run():
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Enceladus")
                    )
                ),
                system_instruction=self._build_tts_system_prompt(),
            )

            async with client.aio.live.connect(
                model="gemini-2.5-flash-native-audio-latest", config=config,
            ) as session:
                prompt = f"قول بعامية مصرية:\n{text}"
                await session.send_client_content(
                    turns=[{"role": "user", "parts": [{"text": prompt}]}],
                    turn_complete=True,
                )
                async for msg in session.receive():
                    sc = getattr(msg, 'server_content', None)
                    if not sc:
                        continue
                    if sc.model_turn and getattr(sc.model_turn, 'parts', None):
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                chunk = part.inline_data.data
                                collected_pcm.append(chunk)
                                if player and not self._tts_muted:
                                    player.feed(chunk)
                    if getattr(sc, 'turn_complete', False):
                        break

        try:
            logger.info(f"Cold-start TTS for '{text[:40]}...'")
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(asyncio.wait_for(_run(), timeout=30.0))
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()

            if player:
                player.done()

            pcm = b"".join(collected_pcm)
            logger.info(f"Cold-start TTS: {len(pcm)} bytes for '{text[:40]}'")
            return pcm

        except Exception as e:
            logger.error(f"Cold-start TTS failed: {e}")
            if player:
                player.done()
            return b""

    def generate_speech(self, text: str, player=None, on_audio_chunk=None) -> bytes:
        """TTS via cold-start WebSocket — reliable one-shot approach.

        Opens a fresh connection, sends text, collects audio, feeds player.
        """
        self._current_tts_player = player
        logger.info(f"generate_speech: cold-start for '{text[:40]}'")
        return self._generate_speech_coldstart(text, player=player)

