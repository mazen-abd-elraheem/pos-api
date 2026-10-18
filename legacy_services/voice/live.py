"""
services/voice/live.py — Real-time bidirectional voice via Gemini Live API.

Contains:
  - LiveSession:       Low-level persistent WebSocket to Gemini Live API.
  - LiveVoiceManager:  High-level push-to-talk manager with mic streaming.

Flow:
  Mic PCM (16kHz) → LiveSession.send_audio() → WebSocket → Gemini
  Gemini → audio chunks (24kHz) + text transcript + tool calls → callbacks
"""
from __future__ import annotations

import json
import logging
import threading
import time as _time
from typing import Any

from .tools import TOOL_DISPATCH

logger = logging.getLogger(__name__)


class LiveSession:
    """Persistent Gemini Live API session. Streams mic PCM in, gets audio+text out."""

    def __init__(self, api_key: str, system_prompt: str,
                 tool_declarations: list, allowed_tools: set):
        self._api_key = api_key
        self._sys_prompt = system_prompt
        self._tool_decls = (
            [t for t in tool_declarations if t["name"] in allowed_tools]
            if allowed_tools else tool_declarations
        )
        self._loop = None
        self._thread = None
        self._q = None          # asyncio.Queue for outbound messages
        self._connected = False

        # Callbacks (set by caller before connect)
        self.on_audio_out = None        # fn(pcm_bytes)
        self.on_text_out = None         # fn(str)
        self.on_turn_done = None        # fn()
        self.on_input_transcript = None # fn(str)
        self.on_connected = None        # fn()
        self.on_error = None            # fn(str)
        self.on_disconnected = None     # fn()

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Thread-safe public API ──

    def connect(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send_audio(self, pcm16k: bytes):
        """Send a 16kHz mono PCM chunk (thread-safe)."""
        if self._connected and self._loop and self._q:
            self._loop.call_soon_threadsafe(self._q.put_nowait, ("audio", pcm16k))

    def end_turn(self):
        """Signal end of user audio (thread-safe)."""
        if self._connected and self._loop and self._q:
            self._loop.call_soon_threadsafe(self._q.put_nowait, ("end", None))

    def send_text(self, text: str):
        """Send text input (thread-safe)."""
        if self._connected and self._loop and self._q:
            self._loop.call_soon_threadsafe(self._q.put_nowait, ("text", text))

    def disconnect(self):
        self._connected = False
        if self._loop and self._q:
            try:
                self._loop.call_soon_threadsafe(self._q.put_nowait, ("stop", None))
            except Exception:
                pass

    # ── Background thread ──

    def _run(self):
        import asyncio
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            logger.error(f"LiveSession fatal: {e}")
            if self.on_error:
                try: self.on_error(str(e))
                except Exception: pass
        finally:
            try: self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception: pass
            self._loop.close()
            self._connected = False

    async def _main(self):
        import asyncio
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            tools=[{"function_declarations": self._tool_decls}] if self._tool_decls else None,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Enceladus")
                )
            ),
            system_instruction=self._sys_prompt,
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

        self._q = asyncio.Queue()

        async with client.aio.live.connect(
            model="gemini-2.5-flash-native-audio-latest", config=config,
        ) as session:
            self._connected = True
            logger.info("LiveSession connected")
            if self.on_connected:
                try: self.on_connected()
                except Exception: pass

            send_task = asyncio.create_task(self._send_loop(session))
            recv_task = asyncio.create_task(self._recv_loop(session))
            done, pending = await asyncio.wait(
                [send_task, recv_task], return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                ex = t.exception()
                if ex:
                    logger.error(f"LiveSession task crashed: {ex}")
            for t in pending:
                t.cancel()

        self._connected = False
        logger.info("LiveSession closed")
        if self.on_disconnected:
            try: self.on_disconnected()
            except Exception: pass

    async def _send_loop(self, session):
        import asyncio
        from google.genai import types

        while self._connected:
            try:
                kind, data = await asyncio.wait_for(self._q.get(), timeout=300)
            except asyncio.TimeoutError:
                continue
            try:
                if kind == "stop":
                    break
                elif kind == "audio":
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    )
                elif kind == "end":
                    await session.send_realtime_input(audio_stream_end=True)
                elif kind == "text":
                    await session.send_client_content(
                        turns=[{"role": "user", "parts": [{"text": data}]}],
                        turn_complete=True,
                    )
            except Exception as e:
                logger.error(f"LiveSession send error ({kind}): {e}")

    async def _recv_loop(self, session):
        from google.genai import types

        try:
            async for msg in session.receive():
                if not self._connected:
                    break
                try:
                    # ── Tool calls ──
                    if msg.tool_call:
                        responses = []
                        for fc in msg.tool_call.function_calls:
                            fn_name = fc.name
                            fn_args = dict(fc.args) if fc.args else {}
                            logger.info(f"Live tool: {fn_name}({fn_args})")
                            tool_fn = TOOL_DISPATCH.get(fn_name)
                            if tool_fn:
                                try:
                                    res = tool_fn(**fn_args)
                                except Exception as e:
                                    res = {"success": False, "error": str(e)}
                            else:
                                res = {"success": False, "error": f"Unknown: {fn_name}"}
                            responses.append(types.FunctionResponse(
                                id=fc.id, name=fn_name,
                                response={"result": json.dumps(res, ensure_ascii=False, default=str)},
                            ))
                        await session.send_tool_response(function_responses=responses)
                        continue

                    # ── Server content ──
                    if not msg.server_content:
                        continue
                    sc = msg.server_content

                    # Model turn — audio chunks
                    if sc.model_turn and getattr(sc.model_turn, 'parts', None):
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                if self.on_audio_out:
                                    try: self.on_audio_out(part.inline_data.data)
                                    except Exception: pass

                    # Output transcription (what model spoke as text)
                    oat = getattr(sc, 'output_audio_transcription', None)
                    if oat:
                        txt = getattr(oat, 'text', None) or (oat if isinstance(oat, str) else None)
                        if txt and self.on_text_out:
                            try: self.on_text_out(txt)
                            except Exception: pass

                    # Input transcription (what user said)
                    iat = getattr(sc, 'input_audio_transcription', None)
                    if iat:
                        txt = getattr(iat, 'text', None) or (iat if isinstance(iat, str) else None)
                        if txt and self.on_input_transcript:
                            try: self.on_input_transcript(txt)
                            except Exception: pass

                    if getattr(sc, 'turn_complete', False):
                        if self.on_turn_done:
                            try: self.on_turn_done()
                            except Exception: pass

                except Exception as e:
                    logger.error(f"LiveSession recv msg error: {e}")
                    continue

        except Exception as e:
            logger.error(f"LiveSession receive stream ended: {e}")


class LiveVoiceManager:
    """Push-to-talk bidirectional voice using a persistent Gemini Live API WebSocket.

    Usage:
        mgr = LiveVoiceManager(api_key, system_prompt, tools, allowed_tools)
        mgr.on_audio_out = lambda pcm: player.feed(pcm)
        mgr.on_text_out  = lambda txt: show_bubble(txt)
        mgr.connect()
        mgr.start_mic()
        mgr.stop_mic()
        mgr.send_text("hello")
        mgr.shutdown()
    """

    SAMPLE_RATE    = 16000
    CHANNELS       = 1
    BLOCK_SIZE     = 3200   # 200ms at 16kHz
    SILENCE_THRESH = 350
    SILENCE_BLOCKS = 5      # 5 × 200ms = 1s silence → auto-stop

    def __init__(self, api_key: str, system_prompt: str,
                 tool_declarations: list, allowed_tools: set):
        self._api_key = api_key
        self._sys_prompt = system_prompt
        self._tool_decls = tool_declarations
        self._allowed_tools = allowed_tools

        self._session: LiveSession | None = None
        self._mic_active = False
        self._mic_thread: threading.Thread | None = None
        self._speech_started = False
        self._silence_count = 0

        # Callbacks (set by UI before connect)
        self.on_audio_out: Any = None
        self.on_text_out: Any = None
        self.on_input_transcript: Any = None
        self.on_turn_done: Any = None
        self.on_connected: Any = None
        self.on_error: Any = None
        self.on_disconnected: Any = None
        self.on_speech_start: Any = None

    @property
    def connected(self) -> bool:
        return self._session is not None and self._session.connected

    @property
    def mic_active(self) -> bool:
        return self._mic_active

    def connect(self):
        """Open persistent WebSocket to Gemini Live API (background thread)."""
        if self._session and self._session.connected:
            logger.info("LiveVoiceManager: already connected")
            return
        self._session = LiveSession(
            api_key=self._api_key, system_prompt=self._sys_prompt,
            tool_declarations=self._tool_decls, allowed_tools=self._allowed_tools,
        )
        self._session.on_audio_out = self._on_audio
        self._session.on_text_out = self._on_text
        self._session.on_input_transcript = self._on_input_transcript
        self._session.on_turn_done = self._on_turn_done
        self._session.on_connected = self._on_connected
        self._session.on_error = self._on_error
        self._session.on_disconnected = self._on_disconnected
        self._session.connect()
        logger.info("LiveVoiceManager: connecting...")

    def start_mic(self):
        """Start streaming mic audio to Live API."""
        if not self.connected:
            logger.warning("LiveVoiceManager: not connected, cannot start mic")
            if self.on_error:
                self.on_error("Not connected to Live API")
            return
        if self._mic_active:
            return
        self._mic_active = True
        self._speech_started = False
        self._silence_count = 0
        self._mic_thread = threading.Thread(target=self._mic_loop, daemon=True)
        self._mic_thread.start()

    def stop_mic(self):
        """Stop mic and signal end of user turn."""
        self._mic_active = False
        if self._session and self._session.connected:
            self._session.end_turn()
            logger.info("LiveVoiceManager: end_turn sent")

    def send_text(self, text: str):
        """Send text input to the Live API session."""
        if not self.connected:
            if self.on_error:
                self.on_error("Not connected")
            return
        self._session.send_text(text)
        logger.info(f"LiveVoiceManager: sent text '{text[:60]}'")

    def shutdown(self):
        """Stop everything and disconnect."""
        self._mic_active = False
        if self._session:
            try: self._session.disconnect()
            except Exception: pass
            self._session = None
        logger.info("LiveVoiceManager: shutdown complete")

    # ── Mic streaming loop ──

    def _mic_loop(self):
        """Stream mic PCM chunks directly to LiveSession.send_audio()."""
        try:
            import sounddevice as sd
            import numpy as np

            def _callback(indata, frames, time_info, status):
                if not self._mic_active:
                    return
                audio = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
                rms = int(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
                if rms > self.SILENCE_THRESH:
                    if not self._speech_started:
                        self._speech_started = True
                        if self.on_speech_start:
                            try: self.on_speech_start()
                            except Exception: pass
                    self._silence_count = 0
                elif self._speech_started:
                    self._silence_count += 1
                    if self._silence_count >= self.SILENCE_BLOCKS:
                        self._mic_active = False
                pcm_bytes = audio.tobytes()
                if self._session and self._session.connected:
                    self._session.send_audio(pcm_bytes)

            with sd.InputStream(
                samplerate=self.SAMPLE_RATE, channels=self.CHANNELS,
                dtype="int16", blocksize=self.BLOCK_SIZE, callback=_callback,
            ):
                while self._mic_active:
                    _time.sleep(0.02)

            if self._speech_started and self._session and self._session.connected:
                self._session.end_turn()
                logger.info("LiveVoiceManager: auto-stop → end_turn sent")

        except ImportError:
            logger.error("sounddevice not installed — pip install sounddevice numpy")
            if self.on_error:
                self.on_error("sounddevice not installed")
        except Exception as e:
            logger.error(f"LiveVoiceManager mic error: {e}")
            if self.on_error:
                self.on_error(str(e))
        finally:
            self._mic_active = False

    # ── Callback proxies ──

    def _on_audio(self, pcm_bytes: bytes):
        if self.on_audio_out:
            try: self.on_audio_out(pcm_bytes)
            except Exception: pass

    def _on_text(self, text: str):
        if self.on_text_out:
            try: self.on_text_out(text)
            except Exception: pass

    def _on_input_transcript(self, text: str):
        if self.on_input_transcript:
            try: self.on_input_transcript(text)
            except Exception: pass

    def _on_turn_done(self):
        if self.on_turn_done:
            try: self.on_turn_done()
            except Exception: pass

    def _on_connected(self):
        logger.info("LiveVoiceManager: WebSocket connected ✓")
        if self.on_connected:
            try: self.on_connected()
            except Exception: pass

    def _on_error(self, err: str):
        logger.error(f"LiveVoiceManager: {err}")
        if self.on_error:
            try: self.on_error(err)
            except Exception: pass

    def _on_disconnected(self):
        logger.warning("LiveVoiceManager: WebSocket disconnected")
        if self.on_disconnected:
            try: self.on_disconnected()
            except Exception: pass
