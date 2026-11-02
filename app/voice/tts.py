"""
Text-to-speech abstraction.

As with STT, kept behind an interface so edge-tts can be swapped for
ElevenLabs, OpenAI TTS, or a local engine later without touching callers.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import sys
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def clean_for_speech(text: str) -> str:
    """Strip markdown and URLs so the voice doesn't read out asterisks,
    hashes and long links."""
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`~|>]", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def split_for_speech(text: str, first_min_chars: int = 12, max_chars: int = 160) -> list[str]:
    """Split text into chunks to synthesize one after another. The first
    chunk is kept short (about one sentence) so speech starts quickly; later
    chunks are merged up to `max_chars` so there are few gaps."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+|\n+", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for part in parts:
        limit = first_min_chars if not chunks else max_chars
        if buf and (len(buf) >= limit or len(buf) + len(part) > max_chars):
            chunks.append(buf)
            buf = part
        else:
            buf = f"{buf} {part}".strip()
    if buf:
        chunks.append(buf)
    return chunks


@dataclass(frozen=True)
class SpeechResult:
    success: bool
    error: str | None = None
    effect_applied: bool = False


class TextToSpeech(ABC):
    @abstractmethod
    async def speak(self, text: str) -> SpeechResult:
        """Synthesize and play back the given text. Blocks until playback finishes."""
        raise NotImplementedError


class EdgeTTSProvider(TextToSpeech):
    """edge-tts (cloud, free, no API key) + pygame.mixer for playback.

    Default voice/rate/pitch aim for a calm, measured British delivery
    (JARVIS-inspired, not a clone of any actor's actual voice — see the
    README for why). `rate` and `pitch` are exposed as edge-tts's own
    relative-adjustment strings (e.g. "-10%", "-2Hz") so they're tunable
    without code changes; see .env.example.

    When `cinematic_effect` is enabled, synthesized audio is post-processed
    with a high-frequency shelf boost (crispness) and a subtle low-rate
    amplitude modulation (faint metallic texture) via app.voice.audio_effects
    before playback. This requires pydub + ffmpeg to decode/re-encode the
    audio; if that processing fails for any reason (ffmpeg missing, etc.),
    playback falls back to the unprocessed audio rather than failing the
    whole response — the effect is a texture, not something worth losing a
    spoken reply over.
    """

    def __init__(
        self,
        voice: str = "en-GB-RyanNeural",
        rate: str = "-10%",
        pitch: str = "-2Hz",
        cinematic_effect: bool = True,
        effect_boost_hz: float = 7000.0,
        effect_boost_db: float = 1.5,
        effect_mod_hz: float = 50.0,
        effect_mod_depth: float = 0.05,
        effect_room: float = 0.0,
    ) -> None:
        self._voice = voice
        self._rate = rate
        self._pitch = pitch
        self._cinematic_effect = cinematic_effect
        self._effect_boost_hz = effect_boost_hz
        self._effect_boost_db = effect_boost_db
        self._effect_mod_hz = effect_mod_hz
        self._effect_mod_depth = effect_mod_depth
        self._effect_room = effect_room
        self._effect_warned = False

    async def speak(self, text: str) -> SpeechResult:
        text = clean_for_speech(text or "")
        if not text:
            return SpeechResult(success=False, error="No text to speak.")

        try:
            import edge_tts  # imported lazily; optional dep
        except ImportError as exc:
            return SpeechResult(success=False, error=f"edge-tts is not installed: {exc}")

        if self._streaming_available():
            return await self._speak_streaming(text, edge_tts)
        return await self._speak_via_file(text, edge_tts)

    # --- Fast path: synthesize sentence by sentence, decode in memory, play
    # through the sound card directly while the next sentence is prepared.

    @staticmethod
    def _streaming_available() -> bool:
        try:
            import av  # noqa: F401 - PyAV ships with faster-whisper
            import numpy  # noqa: F401
            import sounddevice  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    async def _speak_streaming(self, text: str, edge_tts) -> SpeechResult:
        chunks = split_for_speech(text)
        # Synthesize every chunk concurrently (a few at a time) and play them
        # in order: the first sentence starts as soon as it's ready, and the
        # rest are usually done before they're needed, so there are no gaps.
        limiter = asyncio.Semaphore(3)

        async def synthesize(chunk: str):
            async with limiter:
                return await self._synthesize_chunk(edge_tts, chunk)

        tasks = [asyncio.create_task(synthesize(chunk)) for chunk in chunks]
        loop = asyncio.get_running_loop()
        played_any = False
        effect_applied = False
        try:
            for index, task in enumerate(tasks):
                try:
                    samples, sample_rate, effect_applied = await task
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Online voice failed (%s); using the built-in Windows voice.", str(exc).split(",")[0]
                    )
                    fallback_error = await self._speak_with_windows_voice(" ".join(chunks[index:]))
                    if fallback_error is not None and not played_any:
                        return SpeechResult(
                            success=False,
                            error=f"Speech synthesis failed: {exc}. Try: pip install --upgrade edge-tts",
                        )
                    break
                try:
                    await loop.run_in_executor(None, self._play_samples, samples, sample_rate)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Audio playback failed")
                    return SpeechResult(success=False, error=f"Audio playback failed: {exc}")
                played_any = True
        except asyncio.CancelledError:
            self._stop_playback()  # Ctrl+C: stop talking immediately
            raise
        finally:
            for task in tasks:
                task.cancel()
        return SpeechResult(success=True, effect_applied=effect_applied)

    async def _synthesize_chunk(self, edge_tts, chunk: str):
        data = bytearray()
        communicate = edge_tts.Communicate(chunk, self._voice, rate=self._rate, pitch=self._pitch)
        async for message in communicate.stream():
            if message.get("type") == "audio":
                data.extend(message["data"])
        if not data:
            raise RuntimeError("No audio was received from the voice service.")
        return await asyncio.to_thread(self._decode_and_process, bytes(data))

    def _decode_and_process(self, mp3_bytes: bytes):
        """Decode MP3 in-process with PyAV (milliseconds; spawning ffmpeg via
        pydub took ~20s per reply) and apply the cinematic effect in numpy."""
        import av
        import numpy as np

        with av.open(io.BytesIO(mp3_bytes)) as container:
            stream = container.streams.audio[0]
            sample_rate = stream.rate or 24000
            resampler = av.AudioResampler(format="flt", layout="mono", rate=sample_rate)
            pieces = []
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    pieces.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None):  # flush
                pieces.append(out.to_ndarray().reshape(-1))
        samples = np.concatenate(pieces).astype(np.float64) if pieces else np.zeros(0)

        effect_applied = False
        if self._cinematic_effect and samples.size:
            try:
                from app.voice.audio_effects import apply_cinematic_effect

                samples = apply_cinematic_effect(
                    samples,
                    sample_rate,
                    boost_cutoff_hz=self._effect_boost_hz,
                    boost_gain_db=self._effect_boost_db,
                    mod_rate_hz=self._effect_mod_hz,
                    mod_depth=self._effect_mod_depth,
                    room_gain=self._effect_room,
                )
                effect_applied = True
            except Exception as exc:  # noqa: BLE001
                if not self._effect_warned:
                    self._effect_warned = True
                    logger.warning("Cinematic voice effect unavailable, using the plain voice: %s", exc)
        return samples.astype(np.float32), sample_rate, effect_applied

    @staticmethod
    def _play_samples(samples, sample_rate: int) -> None:
        import sounddevice as sd

        sd.play(samples, sample_rate)
        sd.wait()

    @staticmethod
    def _stop_playback() -> None:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:  # noqa: BLE001
            pass

    # --- Fallback path: whole reply to an MP3 file, played with pygame.

    async def _speak_via_file(self, text: str, edge_tts) -> SpeechResult:
        # A unique filename per call, not a fixed shared one: on Windows,
        # pygame's mixer can hold a lingering file lock on the previous
        # mp3 for a moment after playback even after quit(), which made a
        # reused fixed filename intermittently fail to overwrite with
        # PermissionError. Old temp files are best-effort cleaned up after
        # playback rather than relying on a single shared path.
        tmp_path = Path(tempfile.gettempdir()) / f"jarvis_tts_{uuid.uuid4().hex}.mp3"

        try:
            communicate = edge_tts.Communicate(
                text, self._voice, rate=self._rate, pitch=self._pitch
            )
            await communicate.save(str(tmp_path))
        except Exception as exc:  # noqa: BLE001
            # The free Edge voice service occasionally rejects older
            # edge-tts versions (HTTP 403) or is unreachable; fall back to
            # the offline Windows voice rather than going silent.
            logger.warning("Online voice failed (%s); using the built-in Windows voice.", str(exc).split(",")[0])
            tmp_path.unlink(missing_ok=True)
            fallback_error = await self._speak_with_windows_voice(text)
            if fallback_error is None:
                return SpeechResult(success=True)
            return SpeechResult(
                success=False,
                error=f"Speech synthesis failed: {exc}. Try: pip install --upgrade edge-tts",
            )

        playback_path = tmp_path
        effect_applied = False
        if self._cinematic_effect:
            try:
                playback_path = self._apply_cinematic_effect(tmp_path)
                effect_applied = True
            except Exception as exc:  # noqa: BLE001
                # Warn once per session, not after every reply; the plain
                # voice still plays.
                if not self._effect_warned:
                    self._effect_warned = True
                    logger.warning(
                        "Cinematic voice effect unavailable, using the plain voice: %s "
                        "(needs pydub + ffmpeg; set TTS_CINEMATIC_EFFECT=false to silence this)",
                        exc,
                    )

        try:
            self._play(playback_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Audio playback failed")
            return SpeechResult(success=False, error=f"Audio playback failed: {exc}")
        finally:
            for p in {tmp_path, playback_path}:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass  # best effort; a leftover temp file isn't worth failing over

        return SpeechResult(success=True, effect_applied=effect_applied)

    async def _speak_with_windows_voice(self, text: str) -> str | None:
        """Speak via Windows' built-in System.Speech (offline). Text is
        passed on stdin, never interpolated into the script. Returns None
        on success, or an error message."""
        if sys.platform != "win32":
            return "no offline voice on this platform"
        from app.integrations.system_control import run_process

        script = (
            "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "try { $s.SelectVoiceByHints('Male') } catch {}; "
            "$s.Speak([Console]::In.ReadToEnd())"
        )
        out = await run_process(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=300,
            stdin_text=text,
        )
        if out.success:
            return None
        return out.error or out.stderr or "Windows voice failed"

    def _apply_cinematic_effect(self, mp3_path: Path) -> Path:
        """Decode -> apply the high-shelf boost + amplitude modulation ->
        re-encode as a temporary wav. Raises on any failure; the caller
        decides how to degrade gracefully."""
        import numpy as np
        from pydub import AudioSegment

        from app.voice.audio_effects import apply_cinematic_effect

        segment = AudioSegment.from_file(str(mp3_path), format="mp3")
        raw = np.array(segment.get_array_of_samples())
        if segment.channels > 1:
            raw = raw.reshape((-1, segment.channels))

        max_amplitude = float(2 ** (8 * segment.sample_width - 1))
        float_samples = raw.astype(np.float64) / max_amplitude

        processed = apply_cinematic_effect(
            float_samples,
            segment.frame_rate,
            boost_cutoff_hz=self._effect_boost_hz,
            boost_gain_db=self._effect_boost_db,
            mod_rate_hz=self._effect_mod_hz,
            mod_depth=self._effect_mod_depth,
            room_gain=self._effect_room,
        )

        dtype = np.int16 if segment.sample_width == 2 else np.int32
        int_samples = np.clip(
            processed * max_amplitude, -max_amplitude, max_amplitude - 1
        ).astype(dtype)

        processed_segment = AudioSegment(
            int_samples.tobytes(),
            frame_rate=segment.frame_rate,
            sample_width=segment.sample_width,
            channels=segment.channels,
        )

        wav_path = mp3_path.with_suffix(".wav")
        processed_segment.export(str(wav_path), format="wav")
        return wav_path

    def _play(self, path: Path) -> None:
        import time

        import pygame  # imported lazily; optional dep

        pygame.mixer.init()
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        pygame.mixer.music.unload()  # explicitly release the file handle before quit()
        pygame.mixer.quit()
