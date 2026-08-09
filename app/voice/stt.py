"""
Speech-to-text abstraction.

Kept behind an interface for the same reason the LLM provider is:
faster-whisper is today's choice (local, free, no API key), but nothing
outside this module should know that. A cloud STT provider could be
added later as another SpeechToText implementation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptionResult:
    success: bool
    text: str = ""
    error: str | None = None


class SpeechToText(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> TranscriptionResult:
        """Transcribe an audio file on disk (wav) to text."""
        raise NotImplementedError


class WhisperSTT(SpeechToText):
    """faster-whisper-backed implementation.

    The model is loaded lazily on first use (not at construction) so
    importing this module doesn't force a model download/load — useful
    for tests and for keeping app startup fast when voice isn't used.
    """

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8") -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model = None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # imported lazily; heavy + optional dep

            logger.info("Loading faster-whisper model '%s' (first use, may take a moment)...", self._model_size)
            self._model = WhisperModel(self._model_size, device=self._device, compute_type=self._compute_type)
        return self._model

    def transcribe(self, audio_path: str) -> TranscriptionResult:
        try:
            model = self._get_model()
            segments, _info = model.transcribe(audio_path)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:  # noqa: BLE001 - surface honestly, never pretend it worked
            logger.exception("Transcription failed")
            return TranscriptionResult(success=False, error=str(exc))

        if not text:
            return TranscriptionResult(success=False, error="No speech detected in the recording.")

        return TranscriptionResult(success=True, text=text)
