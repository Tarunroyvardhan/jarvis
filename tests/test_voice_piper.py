import pytest

from app.voice.piper_tts import PiperTTSProvider, rate_to_length_scale
from app.voice.tts import split_for_speech


@pytest.mark.parametrize(
    "rate, expected", [("-10%", 1.111), ("+0%", 1.0), ("+25%", 0.8), ("garbage", 1.0)]
)
def test_rate_maps_to_piper_length_scale(rate, expected):
    assert rate_to_length_scale(rate) == expected


def test_unavailable_when_voice_file_missing(tmp_path):
    assert PiperTTSProvider.available(tmp_path / "missing.onnx") is False


@pytest.mark.asyncio
async def test_speaks_every_chunk_in_order(monkeypatch, tmp_path):
    tts = PiperTTSProvider(model_path=tmp_path / "voice.onnx")
    monkeypatch.setattr(tts, "_synthesize", lambda text: (text, 22050))
    played = []
    monkeypatch.setattr(tts, "_play_samples", lambda samples, rate: played.append(samples))

    text = "Opening Chrome now. " + "Here is a longer second part of the reply. " * 5
    result = await tts.speak(text)

    assert result.success is True
    assert played == split_for_speech(text)


@pytest.mark.asyncio
async def test_reports_synthesis_failure(monkeypatch, tmp_path):
    tts = PiperTTSProvider(model_path=tmp_path / "voice.onnx")

    def broken(text):
        raise RuntimeError("model corrupt")

    monkeypatch.setattr(tts, "_synthesize", broken)
    result = await tts.speak("Hello there.")
    assert result.success is False
    assert "model corrupt" in result.error


@pytest.mark.asyncio
async def test_rejects_empty_text(tmp_path):
    result = await PiperTTSProvider(model_path=tmp_path / "v.onnx").speak("  **  ")
    assert result.success is False
