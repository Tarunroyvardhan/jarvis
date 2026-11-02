"""
Central configuration for JARVIS.

All configuration is loaded from environment variables (optionally via a
.env file during local development). Nothing here should ever contain a
real secret — defaults are safe placeholders only.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Load a local .env file if python-dotenv is available and a .env exists.
# This is optional convenience only — real deployments should set real
# environment variables directly. The test suite sets JARVIS_SKIP_DOTENV
# so a developer's real .env can't leak into tests that check defaults.
if not os.getenv("JARVIS_SKIP_DOTENV"):
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - dotenv is an optional convenience
        pass


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    """Read an int env var, falling back to the default (with a warning)
    on a malformed value instead of crashing the whole app at import."""
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    try:
        return int(val.strip())
    except ValueError:
        logger.warning("Ignoring invalid integer for %s=%r; using %s", name, val, default)
        return default


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    try:
        return float(val.strip())
    except ValueError:
        logger.warning("Ignoring invalid number for %s=%r; using %s", name, val, default)
        return default


def _get_str(name: str, default: str) -> str:
    """Like os.getenv, but treats an empty value (`KEY=` in .env) as unset."""
    val = os.getenv(name)
    if val is None or not val.strip():
        return default
    return val.strip()


def _parse_kv_list(raw: str) -> dict[str, str]:
    """Parse 'key1=value1,key2=value2' into a dict. Empty/malformed
    entries are skipped rather than raising, since this only ever backs
    optional allowlists — a typo in one entry shouldn't break config
    loading for everything else.
    """
    result: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            result[key] = value
    return result


def _parse_path_list(raw: str) -> list[Path]:
    return [Path(os.path.expandvars(os.path.expanduser(p.strip()))) for p in raw.split(",") if p.strip()]


@dataclass(frozen=True)
class Settings:
    # Identity
    assistant_name: str = field(default_factory=lambda: _get_str("ASSISTANT_NAME", "Jarvis"))
    # How Jarvis addresses you, e.g. "sir" or your first name. Optional.
    user_name: str = field(default_factory=lambda: _get_str("USER_NAME", ""))

    # LLM provider
    llm_provider: str = field(default_factory=lambda: _get_str("LLM_PROVIDER", "claude"))
    anthropic_api_key: str = field(default_factory=lambda: _get_str("ANTHROPIC_API_KEY", ""))
    claude_model: str = field(default_factory=lambda: _get_str("CLAUDE_MODEL", "claude-opus-5-5"))
    # Thinking counts toward max_tokens, so this must leave room for both
    # reasoning and the reply — values like 1024 truncate answers.
    claude_max_tokens: int = field(default_factory=lambda: _get_int("CLAUDE_MAX_TOKENS", 16000))
    # low | medium | high | xhigh | max — how hard the model thinks.
    claude_effort: str = field(default_factory=lambda: _get_str("CLAUDE_EFFORT", "medium"))
    # Server-side web search/fetch (run by Anthropic, billed per search).
    web_search_enabled: bool = field(default_factory=lambda: _get_bool("WEB_SEARCH_ENABLED", True))
    # Upper bound on tool round-trips in a single request, so a confused
    # model can't loop forever. Multi-step automations need a generous one.
    max_tool_iterations: int = field(default_factory=lambda: _get_int("MAX_TOOL_ITERATIONS", 25))

    # Paths
    data_dir: Path = field(default_factory=lambda: Path(_get_str("JARVIS_DATA_DIR", "data")))

    # Logging
    log_level: str = field(default_factory=lambda: _get_str("LOG_LEVEL", "WARNING"))
    debug: bool = field(default_factory=lambda: _get_bool("JARVIS_DEBUG", False))

    # Voice — all optional; only used if /voice or /wake is invoked
    whisper_model_size: str = field(default_factory=lambda: _get_str("WHISPER_MODEL_SIZE", "base"))
    # Spoken language for transcription ("en", "hi", ...); "auto" detects it.
    whisper_language: str = field(default_factory=lambda: _get_str("WHISPER_LANGUAGE", "en"))
    # Pause length (seconds) that marks the end of a spoken sentence.
    voice_silence_seconds: float = field(default_factory=lambda: _get_float("VOICE_SILENCE_SECONDS", 0.8))
    # "edge"  = Microsoft's natural online voice (TTS_VOICE); starts ~1-2s after the reply.
    # "piper" = offline voice on this laptop; starts instantly but sounds more synthetic.
    tts_engine: str = field(default_factory=lambda: _get_str("TTS_ENGINE", "edge").lower())
    piper_voice: str = field(default_factory=lambda: _get_str("PIPER_VOICE", "en_GB-alan-medium"))
    piper_voice_dir: Path = field(default_factory=lambda: Path(_get_str("PIPER_VOICE_DIR", "data/piper")))
    tts_voice: str = field(default_factory=lambda: _get_str("TTS_VOICE", "en-GB-RyanNeural"))
    tts_rate: str = field(default_factory=lambda: _get_str("TTS_RATE", "-5%"))
    tts_pitch: str = field(default_factory=lambda: _get_str("TTS_PITCH", "-2Hz"))
    # Lower = reacts to more "hey jarvis"-like sounds (and more false alarms).
    # Run /wakecheck in the app to find the right value for your mic and room.
    wake_word_threshold: float = field(default_factory=lambda: _get_float("WAKE_WORD_THRESHOLD", 0.3))
    # Software microphone boost for the wake word (e.g. 2.0 for a quiet laptop mic).
    wake_word_gain: float = field(default_factory=lambda: _get_float("WAKE_WORD_GAIN", 1.0))
    tts_cinematic_effect: bool = field(default_factory=lambda: _get_bool("TTS_CINEMATIC_EFFECT", True))
    tts_effect_boost_hz: float = field(default_factory=lambda: _get_float("TTS_EFFECT_BOOST_HZ", 3500))
    tts_effect_boost_db: float = field(default_factory=lambda: _get_float("TTS_EFFECT_BOOST_DB", 2.0))
    tts_effect_mod_hz: float = field(default_factory=lambda: _get_float("TTS_EFFECT_MOD_HZ", 50))
    # Amplitude "wobble"; above ~0.02 it sounds robotic, so it's off by default.
    tts_effect_mod_depth: float = field(default_factory=lambda: _get_float("TTS_EFFECT_MOD_DEPTH", 0.0))
    # Faint short reflections: a polished, film-AI presence without sounding robotic.
    tts_effect_room: float = field(default_factory=lambda: _get_float("TTS_EFFECT_ROOM", 0.12))

    # Weather & News
    weather_temp_unit: str = field(default_factory=lambda: _get_str("WEATHER_TEMP_UNIT", "fahrenheit"))
    news_feed_urls: list[str] = field(
        default_factory=lambda: [
            url.strip()
            for url in _get_str(
                "NEWS_FEED_URLS",
                "https://feeds.bbci.co.uk/news/world/rss.xml,"
                "https://feeds.npr.org/1001/rss.xml",
            ).split(",")
            if url.strip()
        ]
    )

    # Calendar & Email (Google) — optional; tools only register if
    # credentials.json is present. See README for setup.
    google_credentials_path: Path = field(
        default_factory=lambda: Path(_get_str("GOOGLE_CREDENTIALS_PATH", "credentials.json"))
    )
    google_token_path: Path = field(
        default_factory=lambda: Path(_get_str("GOOGLE_TOKEN_PATH", "data/google_token.json"))
    )

    # Computer control & file intelligence
    allowed_directories: list[Path] = field(
        default_factory=lambda: _parse_path_list(os.getenv("ALLOWED_DIRECTORIES", ""))
    )
    allowed_applications: dict[str, str] = field(
        default_factory=lambda: _parse_kv_list(
            _get_str(
                "ALLOWED_APPLICATIONS",
                "notepad=notepad.exe,calculator=calc.exe,explorer=explorer.exe,vscode=code",
            )
        )
    )
    # project_path=test_command pairs, e.g. "D:\jarvis=python -m pytest -q"
    project_test_commands: dict[str, list[str]] = field(
        default_factory=lambda: {
            path: command.split()
            for path, command in _parse_kv_list(os.getenv("PROJECT_TEST_COMMANDS", "")).items()
        }
    )
    # Shell command execution. Every command is shown to you and needs an
    # explicit "yes" before it runs — this flag only controls whether the
    # tool exists at all.
    shell_enabled: bool = field(default_factory=lambda: _get_bool("SHELL_ENABLED", True))
    shell_timeout_seconds: int = field(default_factory=lambda: _get_int("SHELL_TIMEOUT_SECONDS", 120))

    # Browser automation (Playwright, optional extra). Headed by default so
    # you can watch what Jarvis is doing.
    browser_headless: bool = field(default_factory=lambda: _get_bool("BROWSER_HEADLESS", False))

    # Desktop toast notifications for reminders (Windows).
    desktop_notifications: bool = field(default_factory=lambda: _get_bool("DESKTOP_NOTIFICATIONS", True))

    def validate(self) -> list[str]:
        """Return a list of human-readable problems with the current config."""
        problems: list[str] = []
        if self.llm_provider == "claude" and not self.anthropic_api_key:
            problems.append(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file "
                "(see .env.example)."
            )
        if self.claude_effort not in {"low", "medium", "high", "xhigh", "max"}:
            problems.append(
                f"CLAUDE_EFFORT='{self.claude_effort}' is invalid; use low, medium, high, xhigh or max."
            )
        return problems

    def warnings(self) -> list[str]:
        """Non-fatal config issues worth telling the user about at startup."""
        notes: list[str] = []
        if self.claude_max_tokens < 4096:
            notes.append(
                f"CLAUDE_MAX_TOKENS={self.claude_max_tokens} is very low — thinking counts "
                "toward it, so replies may be cut off. 16000 is recommended."
            )
        if not self.allowed_directories:
            notes.append(
                "ALLOWED_DIRECTORIES is empty, so file tools can't touch anything. "
                "Add folders to .env to enable them."
            )
        return notes


settings = Settings()
