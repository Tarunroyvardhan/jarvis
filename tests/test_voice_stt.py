import sys
import types
from unittest.mock import MagicMock

from app.voice.stt import WhisperSTT


def test_transcribe_reports_missing_dependency_honestly(tmp_path):
    """faster-whisper is an optional extra and isn't installed in the base
    dev environment — transcribe() must report that plainly rather than
    silently returning empty text or crashing the caller."""
    stt = WhisperSTT()
    result = stt.transcribe(str(tmp_path / "doesnt_matter.wav"))

    assert result.success is False
    assert result.error is not None


def test_transcribe_returns_joined_text_on_success(tmp_path, monkeypatch):
    fake_segment_1 = types.SimpleNamespace(text=" hello ")
    fake_segment_2 = types.SimpleNamespace(text=" world ")

    fake_model_instance = MagicMock()
    fake_model_instance.transcribe.return_value = ([fake_segment_1, fake_segment_2], MagicMock())

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = MagicMock(return_value=fake_model_instance)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    stt = WhisperSTT()
    result = stt.transcribe(str(tmp_path / "recording.wav"))

    assert result.success is True
    assert result.text == "hello world"


def test_transcribe_reports_empty_result_as_failure(tmp_path, monkeypatch):
    fake_model_instance = MagicMock()
    fake_model_instance.transcribe.return_value = ([], MagicMock())

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = MagicMock(return_value=fake_model_instance)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    stt = WhisperSTT()
    result = stt.transcribe(str(tmp_path / "silence.wav"))

    assert result.success is False
    assert "No speech detected" in result.error


def test_model_is_loaded_lazily_and_cached(tmp_path, monkeypatch):
    fake_model_instance = MagicMock()
    fake_model_instance.transcribe.return_value = ([], MagicMock())

    fake_module = types.ModuleType("faster_whisper")
    model_constructor = MagicMock(return_value=fake_model_instance)
    fake_module.WhisperModel = model_constructor
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    stt = WhisperSTT()
    assert model_constructor.call_count == 0  # not loaded at construction

    stt.transcribe(str(tmp_path / "a.wav"))
    stt.transcribe(str(tmp_path / "b.wav"))

    assert model_constructor.call_count == 1  # loaded once, reused
