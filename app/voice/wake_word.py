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

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # openWakeWord expects ~80ms frames at 16kHz

DEFAULT_MODEL_NAME = "hey_jarvis"
DEFAULT_THRESHOLD = 0.5


class WakeWordError(Exception):
    pass


class WakeWordDetector:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
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

            try:
                # Downloading with no model_names fetches ALL pretrained
                # wake word models AND the shared preprocessing models
                # (melspectrogram, embedding) that Model() itself needs
                # internally. Passing only [self._model_name] here missed
                # those shared files, so Model() would silently attempt its
                # own download deeper inside __init__ with zero visible
                # progress — which is exactly what looked like a hang.
                # This is a no-op (fast) for anything already cached.
                print(
                    "Downloading wake word model files (first run only, "
                    "may take a minute or two)..."
                )
                openwakeword.utils.download_models()
                print("Model files ready.")
            except Exception as exc:  # noqa: BLE001
                raise WakeWordError(f"Failed to download wake word model files: {exc}") from exc

            print(f"Loading wake word model '{self._model_name}'...")
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

    def score_frame(self, frame) -> float:
        """Score a single audio frame (numpy int16 array) and return the
        wake word's current confidence. Split out from `listen()` so the
        detection threshold logic can be tested without real audio
        hardware, by feeding synthetic frames/scores directly.
        """
        model = self._get_model()
        prediction = model.predict(frame)
        return float(prediction.get(self._model_name, 0.0))

    def listen(self) -> None:
        """Block until the wake word is detected on the default microphone."""
        try:
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

        print("Opening microphone stream...")
        try:
            stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16")
            with stream:
                print('Microphone open — say "Hey Jarvis" now.')
                while True:
                    frame, overflowed = stream.read(FRAME_SAMPLES)
                    if overflowed:
                        logger.warning("Audio input buffer overflowed while listening for wake word.")
                    prediction = model.predict(frame.flatten())
                    score = float(prediction.get(self._model_name, 0.0))
                    if score >= self._threshold:
                        return
        except Exception as exc:  # noqa: BLE001
            raise WakeWordError(f"Wake word listening failed: {exc}") from exc
