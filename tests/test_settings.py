from app.config.settings import Settings


def test_validate_flags_missing_api_key():
    s = Settings(anthropic_api_key="", llm_provider="claude")
    problems = s.validate()
    assert any("ANTHROPIC_API_KEY" in p for p in problems)


def test_validate_passes_with_api_key():
    s = Settings(anthropic_api_key="sk-fake-key-for-test", llm_provider="claude")
    assert s.validate() == []


def test_wake_word_threshold_defaults_to_a_lowered_value():
    """Default threshold is intentionally below openWakeWord's own default
    of 0.5, to improve odds of catching "jarvis" alone rather than only
    the trained "hey jarvis" phrase — see README for the tradeoff."""
    s = Settings()
    assert s.wake_word_threshold == 0.3
    assert s.wake_word_gain == 1.0


def test_parse_kv_list_basic():
    from app.config.settings import _parse_kv_list

    result = _parse_kv_list("a=1,b=2, c = 3 ")
    assert result == {"a": "1", "b": "2", "c": "3"}


def test_parse_kv_list_skips_malformed_entries():
    from app.config.settings import _parse_kv_list

    result = _parse_kv_list("a=1,justakey,=novalue,b=2")
    assert result == {"a": "1", "b": "2"}


def test_parse_kv_list_empty_string():
    from app.config.settings import _parse_kv_list

    assert _parse_kv_list("") == {}


def test_allowed_applications_has_sensible_defaults():
    from app.config.settings import Settings

    s = Settings()
    assert "notepad" in s.allowed_applications
    assert s.allowed_applications["notepad"] == "notepad.exe"


def test_allowed_directories_empty_by_default():
    from app.config.settings import Settings

    s = Settings()
    assert s.allowed_directories == []
