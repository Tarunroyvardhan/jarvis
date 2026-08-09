"""
Central configuration for JARVIS.

All configuration is loaded from environment variables (optionally via a
.env file during local development). Nothing here should ever contain a
real secret — defaults are safe placeholders only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load a local .env file if python-dotenv is available and a .env exists.
# This is optional convenience only — real deployments should set real
# environment variables directly.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is an optional convenience
    pass


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


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


@dataclass(frozen=True)
class Settings:
    # Identity
    assistant_name: str = field(
        default_factory=lambda: os.getenv("ASSISTANT_NAME", "Jarvis")
    )

    # LLM provider
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "claude")
    )
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    claude_model: str = field(
        default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
    )
    claude_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))
    )

    # Conversation behavior
    max_history_messages: int = field(
        default_factory=lambda: int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
    )

    # Paths
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("JARVIS_DATA_DIR", "data"))
    )

    # Logging
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    debug: bool = field(default_factory=lambda: _get_bool("JARVIS_DEBUG", False))

    # Voice (Phase 5) — all optional; only used if /voice is invoked
    whisper_model_size: str = field(
        default_factory=lambda: os.getenv("WHISPER_MODEL_SIZE", "base")
    )
    tts_voice: str = field(
        default_factory=lambda: os.getenv("TTS_VOICE", "en-GB-RyanNeural")
    )
    tts_rate: str = field(
        default_factory=lambda: os.getenv("TTS_RATE", "-10%")
    )
    tts_pitch: str = field(
        default_factory=lambda: os.getenv("TTS_PITCH", "-2Hz")
    )
    wake_word_threshold: float = field(
        default_factory=lambda: float(os.getenv("WAKE_WORD_THRESHOLD", "0.4"))
    )
    tts_cinematic_effect: bool = field(
        default_factory=lambda: _get_bool("TTS_CINEMATIC_EFFECT", True)
    )
    tts_effect_boost_hz: float = field(
        default_factory=lambda: float(os.getenv("TTS_EFFECT_BOOST_HZ", "7000"))
    )
    tts_effect_boost_db: float = field(
        default_factory=lambda: float(os.getenv("TTS_EFFECT_BOOST_DB", "1.5"))
    )
    tts_effect_mod_hz: float = field(
        default_factory=lambda: float(os.getenv("TTS_EFFECT_MOD_HZ", "50"))
    )
    tts_effect_mod_depth: float = field(
        default_factory=lambda: float(os.getenv("TTS_EFFECT_MOD_DEPTH", "0.05"))
    )

    # Weather & News (Phase 7)
    weather_temp_unit: str = field(
        default_factory=lambda: os.getenv("WEATHER_TEMP_UNIT", "fahrenheit")
    )
    news_feed_urls: list[str] = field(
        default_factory=lambda: [
            url.strip()
            for url in os.getenv(
                "NEWS_FEED_URLS",
                "https://feeds.bbci.co.uk/news/world/rss.xml,"
                "https://www.reutersagency.com/feed/?best-topics=top-news",
            ).split(",")
            if url.strip()
        ]
    )

    # Calendar & Email (Google) — optional; tools only register if
    # credentials.json is present. See README for setup.
    google_credentials_path: Path = field(
        default_factory=lambda: Path(os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"))
    )
    google_token_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("GOOGLE_TOKEN_PATH", "data/google_token.json")
        )
    )

    # Computer control & file intelligence (Phase 8)
    allowed_directories: list[Path] = field(
        default_factory=lambda: [
            Path(p.strip())
            for p in os.getenv("ALLOWED_DIRECTORIES", "").split(",")
            if p.strip()
        ]
    )
    allowed_applications: dict[str, str] = field(
        default_factory=lambda: _parse_kv_list(
            os.getenv(
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

    def validate(self) -> list[str]:
        """Return a list of human-readable problems with the current config."""
        problems: list[str] = []
        if self.llm_provider == "claude" and not self.anthropic_api_key:
            problems.append(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file "
                "(see .env.example)."
            )
        return problems


settings = Settings()
