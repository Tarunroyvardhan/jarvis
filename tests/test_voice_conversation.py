import pytest

from app.voice.conversation import extract_command, is_stop_phrase
from app.voice.microphone import UtteranceSegmenter


@pytest.mark.parametrize(
    "heard, expected",
    [
        ("Jarvis, what's the weather?", "what's the weather?"),
        ("What's the weather, Jarvis?", "What's the weather"),
        ("Hey Jarvis open notepad", "open notepad"),
        ("Can you, Jarvis, check my email", "Can you check my email"),
        ("jarvis.", ""),
        ("Javis, what time is it", "what time is it"),
        ("OK Jarvis, lock the screen.", "lock the screen."),
    ],
)
def test_sentences_with_the_name_are_addressed(heard, expected):
    addressed, command = extract_command(heard)
    assert addressed is True
    assert command == expected


@pytest.mark.parametrize(
    "heard",
    ["What's for dinner tonight?", "I was talking to Travis yesterday", "Jarvisland is a place"],
)
def test_other_sentences_are_ignored(heard):
    addressed, _ = extract_command(heard)
    assert addressed is False


def test_custom_assistant_name():
    addressed, command = extract_command("Friday, play some music", name="Friday")
    assert addressed and command == "play some music"


@pytest.mark.parametrize(
    "command", ["stop listening", "Go to sleep.", "goodbye", "stop listening please", "That's all"]
)
def test_stop_phrases(command):
    assert is_stop_phrase(command)


@pytest.mark.parametrize("command", ["stop the music", "what's the weather", "say goodbye to Bob"])
def test_non_stop_phrases(command):
    assert not is_stop_phrase(command)


def _run(segmenter, values):
    return [segmenter.feed(v) for v in values]


def test_segmenter_waits_through_silence_then_captures_one_sentence():
    seg = UtteranceSegmenter(calibration_chunks=3, silence_chunks_needed=3, min_speech_chunks=2)
    states = _run(seg, [50, 50, 50] + [40] * 20 + [900, 900, 900, 100, 900, 100, 100, 100])
    assert states[:23] == ["idle"] * 23
    assert states[-1] == "done"
    assert states.count("done") == 1


def test_segmenter_ignores_a_short_click():
    seg = UtteranceSegmenter(calibration_chunks=1, silence_chunks_needed=3, min_speech_chunks=3)
    states = _run(seg, [50, 900, 50, 50, 50])
    assert "done" not in states
    assert states[-1] == "idle"
    assert seg.speaking is False


def test_segmenter_threshold_adapts_to_noisy_room():
    seg = UtteranceSegmenter(min_threshold=300, noise_multiplier=2.5, calibration_chunks=3)
    _run(seg, [400, 400, 400])
    assert seg.threshold == 1000
    assert seg.feed(600) == "idle"  # background chatter-level, not speech
    assert seg.feed(1500) == "speech"


def test_segmenter_caps_very_long_speech():
    seg = UtteranceSegmenter(calibration_chunks=1, max_speech_chunks=5)
    states = _run(seg, [10] + [900] * 10)
    assert states.index("done") == 5
