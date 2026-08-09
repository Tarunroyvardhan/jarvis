import sys
import types
from unittest.mock import MagicMock

import pytest

from app.voice.tts import EdgeTTSProvider


@pytest.mark.asyncio
async def test_speak_rejects_empty_text():
    tts = EdgeTTSProvider()
    result = await tts.speak("   ")
    assert result.success is False
    assert "No text" in result.error


def test_default_voice_and_rate_favor_natural_sounding_speech():
    """Regression guard: the plain edge-tts defaults (voice-agnostic full
    speed) read noticeably robotic — this locks in the deliberate choice
    of a slower default rate rather than letting it silently drift back."""
    tts = EdgeTTSProvider()
    assert tts._voice == "en-GB-RyanNeural"
    assert tts._rate == "-10%"


@pytest.mark.asyncio
async def test_speak_reports_missing_dependency_honestly(monkeypatch):
    """Force the import to fail regardless of whether edge-tts is actually
    installed in the environment running this test — must stay
    deterministic whether or not `pip install -e ".[voice]"` has been run,
    and critically must never fall through to real network/audio calls
    during a test run."""
    monkeypatch.setitem(sys.modules, "edge_tts", None)

    tts = EdgeTTSProvider()
    result = await tts.speak("hello there")

    assert result.success is False
    assert "edge-tts is not installed" in result.error


@pytest.mark.asyncio
async def test_speak_succeeds_with_mocked_edge_tts_and_playback(monkeypatch, tmp_path):
    # Fake edge_tts.Communicate that "saves" without touching real network/audio.
    fake_communicate_instance = MagicMock()

    async def fake_save(path):
        # actually create the file so downstream code that touches it works
        open(path, "wb").close()

    fake_communicate_instance.save = fake_save

    communicate_constructor = MagicMock(return_value=fake_communicate_instance)
    fake_edge_tts_module = types.ModuleType("edge_tts")
    fake_edge_tts_module.Communicate = communicate_constructor
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts_module)

    tts = EdgeTTSProvider(voice="en-US-AndrewNeural", rate="-10%", pitch="+2Hz")
    # Avoid touching real pygame/audio hardware for playback.
    monkeypatch.setattr(tts, "_play", lambda path: None)

    result = await tts.speak("hello there")

    assert result.success is True
    _, kwargs = communicate_constructor.call_args
    assert kwargs.get("rate") == "-10%"
    assert kwargs.get("pitch") == "+2Hz"


@pytest.mark.asyncio
async def test_speak_uses_unique_filename_per_call_and_cleans_up(monkeypatch):
    """Regression test: reusing one fixed temp filename caused intermittent
    PermissionError on Windows when pygame's mixer still held a file lock
    from the previous call. Each call must use a distinct path, and clean
    up after itself rather than leaving a pile of temp files behind."""
    saved_paths = []

    async def fake_save(path):
        saved_paths.append(path)
        open(path, "wb").close()

    fake_communicate_instance = MagicMock()
    fake_communicate_instance.save = fake_save

    fake_edge_tts_module = types.ModuleType("edge_tts")
    fake_edge_tts_module.Communicate = MagicMock(return_value=fake_communicate_instance)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts_module)

    tts = EdgeTTSProvider()
    monkeypatch.setattr(tts, "_play", lambda path: None)

    await tts.speak("first")
    await tts.speak("second")

    assert len(saved_paths) == 2
    assert saved_paths[0] != saved_paths[1]
    # cleaned up after playback, not left behind
    from pathlib import Path

    assert not Path(saved_paths[0]).exists()
    assert not Path(saved_paths[1]).exists()


@pytest.mark.asyncio
async def test_speak_reports_synthesis_failure(monkeypatch):
    fake_communicate_instance = MagicMock()

    async def failing_save(path):
        raise RuntimeError("network unreachable")

    fake_communicate_instance.save = failing_save

    fake_edge_tts_module = types.ModuleType("edge_tts")
    fake_edge_tts_module.Communicate = MagicMock(return_value=fake_communicate_instance)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts_module)

    tts = EdgeTTSProvider()
    result = await tts.speak("hello there")

    assert result.success is False
    assert "Speech synthesis failed" in result.error


@pytest.mark.asyncio
async def test_speak_reports_playback_failure(monkeypatch):
    fake_communicate_instance = MagicMock()

    async def fake_save(path):
        open(path, "wb").close()

    fake_communicate_instance.save = fake_save

    fake_edge_tts_module = types.ModuleType("edge_tts")
    fake_edge_tts_module.Communicate = MagicMock(return_value=fake_communicate_instance)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts_module)

    tts = EdgeTTSProvider()

    def broken_play(path):
        raise RuntimeError("no audio device")

    monkeypatch.setattr(tts, "_play", broken_play)

    result = await tts.speak("hello there")

    assert result.success is False
    assert "Audio playback failed" in result.error


@pytest.mark.asyncio
async def test_cinematic_effect_applied_when_processing_succeeds(monkeypatch, tmp_path):
    fake_communicate_instance = MagicMock()

    async def fake_save(path):
        open(path, "wb").close()

    fake_communicate_instance.save = fake_save

    fake_edge_tts_module = types.ModuleType("edge_tts")
    fake_edge_tts_module.Communicate = MagicMock(return_value=fake_communicate_instance)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts_module)

    tts = EdgeTTSProvider(cinematic_effect=True)

    processed_path = tmp_path / "processed.wav"
    processed_path.write_bytes(b"fake wav data")
    monkeypatch.setattr(tts, "_apply_cinematic_effect", lambda p: processed_path)

    played_paths = []
    monkeypatch.setattr(tts, "_play", lambda p: played_paths.append(p))

    result = await tts.speak("hello there")

    assert result.success is True
    assert result.effect_applied is True
    assert played_paths == [processed_path]
    assert not processed_path.exists()  # cleaned up after playback


@pytest.mark.asyncio
async def test_cinematic_effect_failure_falls_back_to_unprocessed_playback(monkeypatch):
    """The effect is texture, not core functionality — if processing fails
    (e.g. ffmpeg missing), Jarvis must still speak using the unprocessed
    audio rather than losing the reply entirely."""
    fake_communicate_instance = MagicMock()

    async def fake_save(path):
        open(path, "wb").close()

    fake_communicate_instance.save = fake_save

    fake_edge_tts_module = types.ModuleType("edge_tts")
    fake_edge_tts_module.Communicate = MagicMock(return_value=fake_communicate_instance)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts_module)

    tts = EdgeTTSProvider(cinematic_effect=True)
    monkeypatch.setattr(
        tts, "_apply_cinematic_effect", MagicMock(side_effect=RuntimeError("ffmpeg not found"))
    )

    played_paths = []
    monkeypatch.setattr(tts, "_play", lambda p: played_paths.append(p))

    result = await tts.speak("hello there")

    assert result.success is True
    assert result.effect_applied is False
    assert len(played_paths) == 1  # still played something


@pytest.mark.asyncio
async def test_cinematic_effect_disabled_skips_processing_entirely(monkeypatch):
    fake_communicate_instance = MagicMock()

    async def fake_save(path):
        open(path, "wb").close()

    fake_communicate_instance.save = fake_save

    fake_edge_tts_module = types.ModuleType("edge_tts")
    fake_edge_tts_module.Communicate = MagicMock(return_value=fake_communicate_instance)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts_module)

    tts = EdgeTTSProvider(cinematic_effect=False)
    effect_mock = MagicMock()
    monkeypatch.setattr(tts, "_apply_cinematic_effect", effect_mock)
    monkeypatch.setattr(tts, "_play", lambda p: None)

    result = await tts.speak("hello there")

    assert result.success is True
    assert result.effect_applied is False
    effect_mock.assert_not_called()
