"""
Text-to-speech abstraction.

As with STT, kept behind an interface so edge-tts can be swapped for
ElevenLabs, OpenAI TTS, or a local engine later without touching callers.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._voice = voice
        self._rate = rate
        self._pitch = pitch
        self._cinematic_effect = cinematic_effect
        self._effect_boost_hz = effect_boost_hz
        self._effect_boost_db = effect_boost_db
        self._effect_mod_hz = effect_mod_hz
        self._effect_mod_depth = effect_mod_depth

    async def speak(self, text: str) -> SpeechResult:
        if not text or not text.strip():
            return SpeechResult(success=False, error="No text to speak.")

        try:
            import edge_tts  # imported lazily; optional dep
        except ImportError as exc:
            return SpeechResult(success=False, error=f"edge-tts is not installed: {exc}")

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
            logger.exception("TTS synthesis failed")
            return SpeechResult(success=False, error=f"Speech synthesis failed: {exc}")

        playback_path = tmp_path
        effect_applied = False
        if self._cinematic_effect:
            try:
                playback_path = self._apply_cinematic_effect(tmp_path)
                effect_applied = True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Cinematic voice effect failed, falling back to unprocessed "
                    "audio: %s",
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
