import sys

import pytest

from app.voice.microphone import MicrophoneError, record_push_to_talk, record_until_silence


def _force_audio_deps_missing(monkeypatch):
    """Force sounddevice/numpy imports to fail regardless of what's
    actually installed in the environment running the tests. This must
    stay deterministic — and crucially, must NOT fall through to actually
    opening a real microphone stream or blocking on real input(), which
    would happen (and hang or record real audio) on any machine that has
    genuinely installed the [voice] extra."""
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    monkeypatch.setitem(sys.modules, "numpy", None)


def test_record_push_to_talk_reports_missing_dependency(monkeypatch):
    _force_audio_deps_missing(monkeypatch)

    with pytest.raises(MicrophoneError) as exc_info:
        record_push_to_talk()

    assert "Voice dependencies aren't installed" in str(exc_info.value)
    assert "pip install" in str(exc_info.value)


def test_record_until_silence_reports_missing_dependency(monkeypatch):
    _force_audio_deps_missing(monkeypatch)

    with pytest.raises(MicrophoneError) as exc_info:
        record_until_silence()

    assert "Voice dependencies aren't installed" in str(exc_info.value)
    assert "pip install" in str(exc_info.value)


def test_record_push_to_talk_reports_native_audio_library_missing(monkeypatch):
    """Covers the distinct case of sounddevice being pip-installed but its
    native PortAudio library missing on the system (raises OSError at
    import time, not ImportError) — a real failure mode, not hypothetical:
    it's exactly what happened in this project's own sandbox environment."""
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "sounddevice":
            raise OSError("PortAudio library not found")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(MicrophoneError) as exc_info:
        record_push_to_talk()

    assert "Audio system unavailable" in str(exc_info.value)
