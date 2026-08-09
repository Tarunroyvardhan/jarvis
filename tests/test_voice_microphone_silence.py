from app.voice.microphone import compute_should_stop


def test_does_not_stop_before_speech_starts():
    # all quiet, never spoke -> never stop, no matter how long
    rms_history = [10.0] * 50
    assert compute_should_stop(rms_history, speech_threshold=300.0, silence_chunks_needed=5) is False


def test_does_not_stop_while_still_speaking():
    rms_history = [10.0, 10.0, 500.0, 600.0, 550.0]  # currently mid-speech
    assert compute_should_stop(rms_history, speech_threshold=300.0, silence_chunks_needed=5) is False


def test_stops_after_speech_then_enough_silence():
    rms_history = [10.0, 500.0, 600.0] + [10.0] * 5  # spoke, then 5 quiet chunks
    assert compute_should_stop(rms_history, speech_threshold=300.0, silence_chunks_needed=5) is True


def test_does_not_stop_with_insufficient_trailing_silence():
    rms_history = [10.0, 500.0, 600.0] + [10.0] * 3  # only 3 quiet chunks, need 5
    assert compute_should_stop(rms_history, speech_threshold=300.0, silence_chunks_needed=5) is False


def test_stop_resets_if_speech_resumes_within_trailing_window():
    # spoke, went quiet for a couple chunks, then spoke again — the most
    # recent window isn't all silence, so it should not stop yet
    rms_history = [500.0, 10.0, 10.0, 500.0, 10.0]
    assert compute_should_stop(rms_history, speech_threshold=300.0, silence_chunks_needed=5) is False
