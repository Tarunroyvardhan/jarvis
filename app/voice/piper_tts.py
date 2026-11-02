"""
Offline text-to-speech with Piper (https://github.com/OHF-Voice/piper1-gpl).

Piper runs a small neural voice locally on the CPU: once warmed up it
produces a sentence in well under half a second, versus 1-2 seconds of
network round trip for the online Edge voice. That makes it the default
for spoken replies; the Edge voice remains available (TTS_ENGINE=edge)
and is used automatically if Piper or its voice file is missing.

Voices are .onnx files (+ .onnx.json) in data/piper. Download more with:
    python -m piper.download_voices --download-dir data/piper en_GB-alan-medium
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from app.voice.tts import SpeechResult, TextToSpeech, clean_for_speech, split_for_speech

logger = logging.getLogger(__name__)


def rate_to_length_scale(rate: str) -> float:
    """Map an edge-tts style rate ("-10%", "+5%") to Piper's length_scale
    (>1 is slower), so TTS_RATE works for both engines."""
    try:
        percent = float(rate.strip().rstrip("%"))
    except (ValueError, AttributeError):
        return 1.0
    return round(1.0 / max(0.3, 1.0 + percent / 100.0), 3)


class PiperTTSProvider(TextToSpeech):
    def __init__(
        self,
        model_path: Path,
        rate: str = "-10%",
        cinematic_effect: bool = True,
        effect_boost_hz: float = 7000.0,
        effect_boost_db: float = 1.5,
        effect_mod_hz: float = 50.0,
        effect_mod_depth: float = 0.05,
        effect_room: float = 0.0,
    ) -> None:
        self._model_path = Path(model_path)
        self._length_scale = rate_to_length_scale(rate)
        self._cinematic_effect = cinematic_effect
        self._effect_args = {
            "boost_cutoff_hz": effect_boost_hz,
            "boost_gain_db": effect_boost_db,
            "mod_rate_hz": effect_mod_hz,
            "mod_depth": effect_mod_depth,
            "room_gain": effect_room,
        }
        self._voice = None
        self._load_lock = threading.Lock()
        self._effect_warned = False

    @staticmethod
    def available(model_path: Path) -> bool:
        try:
            import piper  # noqa: F401
            import sounddevice  # noqa: F401
        except (ImportError, OSError):
            return False
        return Path(model_path).exists() and Path(f"{model_path}.json").exists()

    def warm_up(self) -> None:
        """Load the voice and run one throwaway synthesis (the first call
        is ~2s slower than the rest). Blocking: call from a worker thread."""
        self._synthesize("Ready.")

    def _get_voice(self):
        with self._load_lock:
            if self._voice is None:
                from piper import PiperVoice

                logger.info("Loading Piper voice %s", self._model_path.name)
                self._voice = PiperVoice.load(str(self._model_path))
            return self._voice

    def _synthesize(self, text: str):
        """Text -> (float32 samples, sample_rate), with the cinematic effect."""
        import numpy as np
        from piper import SynthesisConfig

        voice = self._get_voice()
        config = SynthesisConfig(length_scale=self._length_scale)
        chunks = list(voice.synthesize(text, syn_config=config))
        if not chunks:
            return np.zeros(0, dtype=np.float32), 22050
        sample_rate = chunks[0].sample_rate
        samples = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float64)

        if self._cinematic_effect and samples.size:
            try:
                from app.voice.audio_effects import apply_cinematic_effect

                samples = apply_cinematic_effect(samples, sample_rate, **self._effect_args)
            except Exception as exc:  # noqa: BLE001
                if not self._effect_warned:
                    self._effect_warned = True
                    logger.warning("Cinematic voice effect unavailable, using the plain voice: %s", exc)
        return samples.astype(np.float32), sample_rate

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

    async def speak(self, text: str) -> SpeechResult:
        text = clean_for_speech(text or "")
        if not text:
            return SpeechResult(success=False, error="No text to speak.")

        chunks = split_for_speech(text)
        loop = asyncio.get_running_loop()
        # Synthesize the next chunk while the current one plays.
        pending = loop.run_in_executor(None, self._synthesize, chunks[0])
        try:
            for index in range(len(chunks)):
                try:
                    samples, sample_rate = await pending
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Piper synthesis failed")
                    return SpeechResult(success=False, error=f"Offline voice failed: {exc}")
                if index + 1 < len(chunks):
                    pending = loop.run_in_executor(None, self._synthesize, chunks[index + 1])
                try:
                    await loop.run_in_executor(None, self._play_samples, samples, sample_rate)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Audio playback failed")
                    return SpeechResult(success=False, error=f"Audio playback failed: {exc}")
        except asyncio.CancelledError:
            self._stop_playback()  # Ctrl+C: stop talking immediately
            raise
        return SpeechResult(success=True, effect_applied=self._cinematic_effect)
