"""
services/voice/audio.py — Audio playback utilities.

Provides _play_wav_bytes (raw PCM) and _play_wav_file (WAV/MP3 file)
with fallback chain: pyaudio → pygame → Windows MCI.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
import time as _time
import wave as _wave

logger = logging.getLogger(__name__)


def _play_wav_bytes(pcm_bytes: bytes, sample_rate: int = 24000) -> None:
    """Play raw PCM bytes (16-bit mono). Tries pyaudio → pygame → OS fallback."""
    if not pcm_bytes:
        return

    # Try pyaudio first
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16, channels=1,
            rate=sample_rate, output=True, frames_per_buffer=4800,
        )
        chunk = 9600
        for i in range(0, len(pcm_bytes), chunk):
            stream.write(pcm_bytes[i:i + chunk])
        stream.stop_stream()
        stream.close()
        pa.terminate()
        return
    except ImportError:
        pass

    # Fallback: save as WAV and play with pygame or OS
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    wav_data = buf.getvalue()

    path = os.path.join(tempfile.gettempdir(), f"va_play_{int(_time.time()*1000)}.wav")
    with open(path, "wb") as f:
        f.write(wav_data)

    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            _time.sleep(0.1)
    except Exception:
        # OS fallback
        import sys
        try:
            if sys.platform == "win32":
                import ctypes
                w = ctypes.windll.winmm
                alias = f"va_{int(_time.time()*1000)}"
                w.mciSendStringW(f'open "{path}" alias {alias}', None, 0, 0)
                w.mciSendStringW(f'play {alias} wait', None, 0, 0)
                w.mciSendStringW(f'close {alias}', None, 0, 0)
        except Exception as e:
            logger.warning(f"_play_wav_bytes all fallbacks failed: {e}")
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def _play_wav_file(file_path: str) -> None:
    """Play an audio file (WAV or MP3) using pygame or Windows MCI fallback."""
    if not file_path or not os.path.exists(file_path):
        return

    # Try pygame first
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            _time.sleep(0.1)
        return
    except Exception:
        pass

    # Windows MCI fallback
    try:
        import sys
        if sys.platform == "win32":
            import ctypes
            w = ctypes.windll.winmm
            alias = f"va_file_{int(_time.time()*1000)}"
            buf = ctypes.create_unicode_buffer(256)
            w.mciSendStringW(f'close {alias}', None, 0, 0)
            err = w.mciSendStringW(f'open "{file_path}" type mpegvideo alias {alias}', buf, 255, 0)
            if err != 0:
                err = w.mciSendStringW(f'open "{file_path}" alias {alias}', buf, 255, 0)
            if err == 0:
                w.mciSendStringW(f'play {alias} wait', None, 0, 0)
                w.mciSendStringW(f'close {alias}', None, 0, 0)
                logger.info(f"Played audio: {file_path}")
            else:
                logger.warning(f"MCI play failed (err={err}): {file_path}")
    except Exception as e:
        logger.warning(f"_play_wav_file failed: {e}")
