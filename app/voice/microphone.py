"""
Microphone recording: push-to-talk and silence-triggered auto-stop.

Both recording functions are synchronous and blocking by design — meant
to run inside `loop.run_in_executor(...)` from the async CLI, the same
pattern already used for regular text input, so they don't freeze the
reminder scheduler while recording.
"""

from __future__ import annotations

import logging
import tempfile
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # Hz — what faster-whisper (and openWakeWord) expect
CHANNELS = 1
CHUNK_SAMPLES = 1600  # 0.1s chunks at 16kHz, used for silence detection


class MicrophoneError(Exception):
    pass


def _import_audio_deps():
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise MicrophoneError(
            f"Voice dependencies aren't installed: {exc}. "
            "Install with: pip install -e \".[voice]\""
        ) from exc
    except OSError as exc:
        raise MicrophoneError(
            f"Audio system unavailable ({exc}). Check that your microphone "
            "drivers are installed and accessible."
        ) from exc
    return np, sd


def _write_wav(audio, samplerate: int, path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16 = 2 bytes
        wf.setframerate(samplerate)
        wf.writeframes(audio.tobytes())


def record_push_to_talk(samplerate: int = SAMPLE_RATE) -> str:
    """Record from the default microphone until the user presses Enter again.

    Returns the path to a temporary 16-bit PCM WAV file. Raises
    MicrophoneError on any failure (missing device, missing dependency,
    etc.) rather than returning a half-written file.
    """
    np, sd = _import_audio_deps()

    frames: list = []

    def _callback(indata, frame_count, time_info, status):  # noqa: ANN001 - sounddevice callback signature
        if status:
            logger.warning("Audio input status: %s", status)
        frames.append(indata.copy())

    print("Recording... press Enter to stop.")
    try:
        with sd.InputStream(
            samplerate=samplerate, channels=CHANNELS, dtype="int16", callback=_callback
        ):
            input()  # blocks this thread only — see module docstring
    except Exception as exc:  # noqa: BLE001
        raise MicrophoneError(f"Could not record audio: {exc}") from exc

    if not frames:
        raise MicrophoneError("No audio was captured.")

    audio = np.concatenate(frames, axis=0)
    tmp_path = Path(tempfile.gettempdir()) / "jarvis_recording.wav"
    _write_wav(audio, samplerate, tmp_path)
    return str(tmp_path)


def compute_should_stop(
    rms_history: list[float],
    speech_threshold: float,
    silence_chunks_needed: int,
) -> bool:
    """Pure decision function for silence-triggered auto-stop, extracted so
    it can be unit tested without any audio hardware.

    Rule: don't stop until speech has actually started (at least one chunk
    above threshold), and then only once `silence_chunks_needed`
    consecutive chunks below threshold have followed.
    """
    started_speaking = any(r >= speech_threshold for r in rms_history)
    if not started_speaking:
        return False

    if len(rms_history) < silence_chunks_needed:
        return False

    trailing = rms_history[-silence_chunks_needed:]
    return all(r < speech_threshold for r in trailing)


def record_until_silence(
    samplerate: int = SAMPLE_RATE,
    max_seconds: float = 15.0,
    silence_seconds: float = 1.5,
    speech_threshold: float = 300.0,
) -> str:
    """Record from the default microphone, auto-stopping once the user has
    spoken and then gone quiet for `silence_seconds`, or after
    `max_seconds` regardless (a hard ceiling so a stuck/noisy mic can't
    record forever).

    Returns the path to a temporary 16-bit PCM WAV file.
    """
    np, sd = _import_audio_deps()

    frames: list = []
    rms_history: list[float] = []
    silence_chunks_needed = max(1, int(silence_seconds / (CHUNK_SAMPLES / samplerate)))
    max_chunks = max(1, int(max_seconds / (CHUNK_SAMPLES / samplerate)))

    try:
        stream = sd.InputStream(samplerate=samplerate, channels=CHANNELS, dtype="int16")
        with stream:
            for _ in range(max_chunks):
                chunk, overflowed = stream.read(CHUNK_SAMPLES)
                if overflowed:
                    logger.warning("Audio input buffer overflowed during recording.")
                frames.append(chunk.copy())
                rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
                rms_history.append(rms)

                if compute_should_stop(rms_history, speech_threshold, silence_chunks_needed):
                    break
    except Exception as exc:  # noqa: BLE001
        raise MicrophoneError(f"Could not record audio: {exc}") from exc

    if not frames:
        raise MicrophoneError("No audio was captured.")

    audio = np.concatenate(frames, axis=0)
    tmp_path = Path(tempfile.gettempdir()) / "jarvis_recording.wav"
    _write_wav(audio, samplerate, tmp_path)
    return str(tmp_path)


class RecordingStopped(Exception):
    """record_utterance() was asked to stop via its stop_event."""


class UtteranceSegmenter:
    """Pure state machine that splits a stream of audio-chunk loudness
    values into one utterance: idle until speech starts, then speaking
    until enough trailing silence. Extracted from record_utterance() so
    the logic is testable without a microphone.

    The speech threshold adapts to the room: the first `calibration_chunks`
    measure background noise, and speech must be clearly louder than that
    (but never quieter than `min_threshold`).
    """

    def __init__(
        self,
        min_threshold: float = 300.0,
        noise_multiplier: float = 2.5,
        calibration_chunks: int = 3,
        silence_chunks_needed: int = 8,
        min_speech_chunks: int = 3,
        max_speech_chunks: int = 300,
    ) -> None:
        self.min_threshold = min_threshold
        self.noise_multiplier = noise_multiplier
        self.calibration_chunks = calibration_chunks
        self.silence_chunks_needed = silence_chunks_needed
        self.min_speech_chunks = min_speech_chunks
        self.max_speech_chunks = max_speech_chunks
        self._noise_samples: list[float] = []
        self.threshold = min_threshold
        self.speaking = False
        self._speech_chunks = 0
        self._loud_chunks = 0
        self._silent_run = 0

    def feed(self, rms: float) -> str:
        """Feed one chunk's RMS. Returns "idle" (no speech yet; caller may
        keep it as lead-in), "speech" (part of the utterance), or "done"
        (utterance complete, including this chunk)."""
        if len(self._noise_samples) < self.calibration_chunks and not self.speaking:
            self._noise_samples.append(rms)
            # The quietest chunk, not the median: if the user starts talking
            # straight after the wake word (or over the chime), their voice
            # must not be mistaken for background noise.
            noise = min(self._noise_samples)
            self.threshold = max(self.min_threshold, noise * self.noise_multiplier)
            return "idle"

        if not self.speaking:
            if rms >= self.threshold:
                self.speaking = True
                self._speech_chunks = 1
                self._loud_chunks = 1
                return "speech"
            return "idle"

        self._speech_chunks += 1
        if rms >= self.threshold:
            self._loud_chunks += 1
            self._silent_run = 0
        else:
            self._silent_run += 1

        if self._speech_chunks >= self.max_speech_chunks:
            return "done"
        if self._silent_run >= self.silence_chunks_needed:
            if self._loud_chunks < self.min_speech_chunks:
                # A click or cough, not speech: go back to waiting.
                self.speaking = False
                self._speech_chunks = self._loud_chunks = self._silent_run = 0
                return "idle"
            return "done"
        return "speech"


def record_utterance(
    stop_event=None,
    samplerate: int = SAMPLE_RATE,
    silence_seconds: float = 0.8,
    max_seconds: float = 30.0,
    pre_roll_seconds: float = 0.4,
    min_threshold: float = 300.0,
) -> str:
    """Wait (indefinitely) for the user to start speaking, record until they
    pause for `silence_seconds`, and return a WAV path for that sentence.

    Keeps a short lead-in from before speech was detected so the first
    syllable isn't clipped. Raises RecordingStopped if `stop_event` (a
    threading.Event) is set while waiting/recording, MicrophoneError on
    audio failures.
    """
    from collections import deque

    np, sd = _import_audio_deps()

    chunk_seconds = CHUNK_SAMPLES / samplerate
    segmenter = UtteranceSegmenter(
        min_threshold=min_threshold,
        silence_chunks_needed=max(1, int(silence_seconds / chunk_seconds)),
        max_speech_chunks=max(1, int(max_seconds / chunk_seconds)),
    )
    pre_roll: deque = deque(maxlen=max(1, int(pre_roll_seconds / chunk_seconds)))
    frames: list = []

    try:
        with sd.InputStream(samplerate=samplerate, channels=CHANNELS, dtype="int16") as stream:
            while True:
                if stop_event is not None and stop_event.is_set():
                    raise RecordingStopped()
                chunk, overflowed = stream.read(CHUNK_SAMPLES)
                if overflowed:
                    logger.debug("Audio input buffer overflowed.")
                chunk = chunk.copy()
                rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
                state = segmenter.feed(rms)
                if state == "idle":
                    if frames:  # false start (a click) — discard it
                        frames = []
                    pre_roll.append(chunk)
                    continue
                if not frames:
                    frames.extend(pre_roll)
                    pre_roll.clear()
                frames.append(chunk)
                if state == "done":
                    break
    except RecordingStopped:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MicrophoneError(f"Could not record audio: {exc}") from exc

    audio = np.concatenate(frames, axis=0)
    tmp_path = Path(tempfile.gettempdir()) / "jarvis_utterance.wav"
    _write_wav(audio, samplerate, tmp_path)
    return str(tmp_path)
