"""
Wake word detection using openWakeWord's pretrained "hey_jarvis" model.

Like the other voice modules, this is synchronous/blocking by design and
meant to run inside `loop.run_in_executor(...)`. `listen()` blocks until
the wake word is detected (or the caller's thread is interrupted), then
returns — it doesn't itself trigger recording or transcription; that's
the caller's job, keeping this module's only responsibility "notice the
wake word."
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # openWakeWord expects ~80ms frames at 16kHz

DEFAULT_MODEL_NAME = "hey_jarvis"
DEFAULT_THRESHOLD = 0.5

# A near-miss is a score of at least this fraction of the threshold. Several
# near-misses in a row also count as a detection: openWakeWord's score for
# a real (but quiet, fast or accented) "hey jarvis" often hovers just under
# the threshold for a few frames instead of spiking above it.
NEAR_MISS_FRACTION = 0.6
NEAR_MISS_FRAMES_NEEDED = 2
NEAR_MISS_WINDOW = 3


def should_trigger(recent_scores: Sequence[float], threshold: float) -> bool:
    """Pure decision rule (no audio), so it can be unit tested."""
    if not recent_scores:
        return False
    if recent_scores[-1] >= threshold:
        return True
    window = list(recent_scores)[-NEAR_MISS_WINDOW:]
    near = threshold * NEAR_MISS_FRACTION
    return sum(1 for s in window if s >= near) >= NEAR_MISS_FRAMES_NEEDED


class WakeWordError(Exception):
    pass


class WakeWordStopped(Exception):
    """listen() was asked to stop via its stop_event."""


class WakeWordDetector:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        threshold: float = DEFAULT_THRESHOLD,
        gain: float = 1.0,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        # Software amplification for quiet laptop microphones.
        self._gain = gain
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                import openwakeword.utils
                from openwakeword.model import Model
            except ImportError as exc:
                raise WakeWordError(
                    f"Voice dependencies aren't installed: {exc}. "
                    "Install with: pip install -e \".[voice]\""
                ) from exc

            if not self._model_files_present():
                try:
                    # Downloading with no model_names fetches ALL pretrained
                    # wake word models AND the shared preprocessing models
                    # (melspectrogram, embedding) that Model() itself needs
                    # internally; passing only [self._model_name] missed
                    # those, so Model() silently downloaded them itself with
                    # no visible progress, which looked like a hang.
                    print(
                        "Downloading wake word model files (first run only, "
                        "may take a minute or two)..."
                    )
                    openwakeword.utils.download_models()
                    print("Model files downloaded.")
                except Exception as exc:  # noqa: BLE001
                    raise WakeWordError(f"Failed to download wake word model files: {exc}") from exc

            logger.info("Loading openWakeWord model '%s'...", self._model_name)
            try:
                # openWakeWord defaults to the tflite backend, but
                # tflite-runtime has no prebuilt wheel for Windows at all
                # (only Linux/Mac), so we force onnx explicitly — onnxruntime
                # is cross-platform and already in the [voice] extra.
                self._model = Model(
                    wakeword_models=[self._model_name], inference_framework="onnx"
                )
            except Exception as exc:  # noqa: BLE001
                raise WakeWordError(f"Failed to load wake word model: {exc}") from exc
        return self._model

    def _model_files_present(self) -> bool:
        """True if the ONNX files this detector needs are already on disk,
        so the download step (and its message) can be skipped."""
        try:
            from pathlib import Path

            import openwakeword

            models_dir = Path(openwakeword.__file__).parent / "resources" / "models"
            needed = ["melspectrogram.onnx", "embedding_model.onnx"]
            return all((models_dir / n).exists() for n in needed) and any(
                models_dir.glob(f"{self._model_name}*.onnx")
            )
        except Exception:  # noqa: BLE001 - when unsure, let download_models() check
            return False

    def score_frame(self, frame) -> float:
        """Score a single audio frame (numpy int16 array) and return the
        wake word's current confidence. Split out from `listen()` so the
        detection threshold logic can be tested without real audio
        hardware, by feeding synthetic frames/scores directly.
        """
        model = self._get_model()
        prediction = model.predict(frame)
        return float(prediction.get(self._model_name, 0.0))

    def listen(self, stop_event=None) -> None:
        """Block until the wake word is detected on the default microphone.

        `stop_event` (a threading.Event) lets the caller end listening
        cleanly — Ctrl+C only reaches the main thread, never this worker
        thread, so without it the microphone would stay open forever.
        """
        recent: deque[float] = deque(maxlen=NEAR_MISS_WINDOW)

        def on_score(score: float, _rms: float) -> bool:
            recent.append(score)
            return should_trigger(recent, self._threshold)

        self._run(on_score, stop_event, ready_message='🎙  Ready: say "Hey Jarvis"')

    def measure(self, seconds: float = 10.0, stop_event=None) -> tuple[list[float], float]:
        """Listen for `seconds` and return (the peak wake-word score of each
        ~1-second window, the loudest frame's RMS level — i.e. how loud the
        user's speech arrives). Used by /wakecheck to suggest settings."""
        frames_per_window = max(1, int(1.0 / (FRAME_SAMPLES / SAMPLE_RATE)))
        total_frames = int(seconds * SAMPLE_RATE / FRAME_SAMPLES)
        peaks: list[float] = []
        loudness: list[float] = []
        state = {"n": 0, "peak": 0.0}

        def on_score(score: float, rms: float) -> bool:
            state["n"] += 1
            state["peak"] = max(state["peak"], score)
            loudness.append(rms)
            if state["n"] % frames_per_window == 0:
                peaks.append(state["peak"])
                state["peak"] = 0.0
            return state["n"] >= total_frames

        self._run(on_score, stop_event)
        return peaks, (max(loudness) if loudness else 0.0)

    def _run(
        self,
        on_score: Callable[[float, float], bool],
        stop_event=None,
        ready_message: str | None = None,
    ) -> None:
        """Feed microphone frames to the model until on_score returns True."""
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise WakeWordError(
                f"Voice dependencies aren't installed: {exc}. "
                "Install with: pip install -e \".[voice]\""
            ) from exc
        except OSError as exc:
            raise WakeWordError(
                f"Audio system unavailable ({exc}). Check that your microphone "
                "drivers are installed and accessible."
            ) from exc

        model = self._get_model()  # load before opening the stream
        if hasattr(model, "reset"):
            model.reset()  # don't carry scores over from the last session

        try:
            # A small device blocksize keeps the delay between you speaking
            # and the model seeing the audio to roughly one frame.
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES
            )
            with stream:
                if ready_message:
                    print(ready_message, flush=True)
                while True:
                    if stop_event is not None and stop_event.is_set():
                        raise WakeWordStopped()
                    frame, overflowed = stream.read(FRAME_SAMPLES)
                    if overflowed:
                        logger.debug("Audio input buffer overflowed while listening for wake word.")
                    samples = frame.flatten()
                    if self._gain != 1.0:
                        samples = np.clip(samples.astype(np.float32) * self._gain, -32768, 32767).astype(np.int16)
                    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                    prediction = model.predict(samples)
                    score = float(prediction.get(self._model_name, 0.0))
                    if on_score(score, rms):
                        # Clear the model's rolling buffer, otherwise the tail
                        # of this utterance re-triggers the next listen().
                        if hasattr(model, "reset"):
                            model.reset()
                        return
        except WakeWordStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            raise WakeWordError(f"Wake word listening failed: {exc}") from exc
