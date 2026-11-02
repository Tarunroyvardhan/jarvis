"""
Decides whether a transcribed sentence was addressed to Jarvis.

Once woken with "Hey Jarvis", the hands-free loop transcribes everything
it hears but only acts on sentences that contain the assistant's name,
so ordinary conversation in the room is ignored. Whisper doesn't always
spell the name the same way, so a few common mis-hearings count too.

Pure string logic, no audio — fully unit-testable.
"""

from __future__ import annotations

import re

# Common Whisper renderings of "Jarvis".
_NAME_VARIANTS = ["jarvis", "jarvas", "jarves", "jarvys", "jervis", "javis", "jarvi", "jarviss"]

# Phrases that end the always-listening session (checked after the name
# has been removed, e.g. "Jarvis, stop listening").
_STOP_PHRASES = [
    "stop listening",
    "go to sleep",
    "sleep mode",
    "that's all",
    "that is all",
    "goodbye",
    "good bye",
    "bye",
    "you can stop",
    "stop",
]


def _name_pattern(name: str) -> re.Pattern[str]:
    variants = set(_NAME_VARIANTS) | {name.lower()}
    alternatives = "|".join(sorted((re.escape(v) for v in variants), key=len, reverse=True))
    return re.compile(rf"\b(?:hey|hi|ok|okay|yo)?[\s,]*(?:{alternatives})\b[\s,.!?:;-]*", re.IGNORECASE)


def extract_command(text: str, name: str = "Jarvis") -> tuple[bool, str]:
    """Return (addressed, command).

    `addressed` is True if the sentence mentions the assistant's name
    anywhere. `command` is the sentence with the name (and a leading
    "hey"/"ok") removed and stray punctuation tidied, e.g.
    "Jarvis, what's the weather?" -> (True, "what's the weather?")
    "What's the weather, Jarvis?" -> (True, "What's the weather?")
    """
    pattern = _name_pattern(name)
    if not pattern.search(text):
        return False, text.strip()
    command = pattern.sub(" ", text)
    command = re.sub(r"\s+([,.!?])", r"\1", command)
    command = re.sub(r"\s+", " ", command).strip(" ,;:-")
    return True, command


def is_stop_phrase(command: str) -> bool:
    """True if the (name-stripped) command asks Jarvis to stop listening."""
    cleaned = re.sub(r"[^\w\s']", "", command.lower()).strip()
    cleaned = re.sub(r"^(please|ok|okay|thanks|thank you)\s+", "", cleaned)
    cleaned = re.sub(r"\s+(please|now|for now|thanks|thank you)$", "", cleaned)
    return cleaned in _STOP_PHRASES
