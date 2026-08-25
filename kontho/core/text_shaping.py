"""Deterministic cleanup between STT and the keyboard.

Strictly rule-based. No LLM touches dictated text - a model that "improves"
`git status` into `Git status.` breaks the thing the user was doing.

Three passes:
  1. vocabulary  - fix domain words STT reliably mangles ("go dot" -> "Godot")
  2. commands    - optional spoken punctuation ("new line" -> \\n)
  3. profile     - capitalisation and spacing appropriate to the target
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .settings import PROFILE_CHAT, PROFILE_DEVELOPER, PROFILE_NORMAL, PROFILE_TERMINAL

log = logging.getLogger("kontho.text")

# Shipped defaults. The user's own entries are merged over these.
DEFAULT_REPLACEMENTS: dict[str, str] = {
    "go dot": "Godot",
    "godot engine": "Godot",
    "pie side six": "PySide6",
    "pyside six": "PySide6",
    "pie side": "PySide",
    "g g u f": "GGUF",
    "gguf": "GGUF",
    "comfy u i": "ComfyUI",
    "comfy ui": "ComfyUI",
    "cuda": "CUDA",
    "quen": "Qwen",
    "qwen": "Qwen",
    "git hub": "GitHub",
    "github": "GitHub",
    "whisper cpp": "whisper.cpp",
    "crea": "Krea",
    "krea": "Krea",
    "python": "Python",
    "numpy": "NumPy",
    "json": "JSON",
    "api": "API",
    "ui": "UI",
    "vram": "VRAM",
    "gpu": "GPU",
    "cpu": "CPU",
}

# Spoken punctuation. Off unless the user turns commands on, because these are
# ordinary words people also dictate literally.
VOICE_COMMANDS: dict[str, str] = {
    "new line": "\n",
    "newline": "\n",
    "new paragraph": "\n\n",
    "full stop": ".",
    "period": ".",
    "comma": ",",
    "question mark": "?",
    "exclamation mark": "!",
    "colon": ":",
    "semicolon": ";",
    "open bracket": "(",
    "close bracket": ")",
}


@dataclass
class ShapingConfig:
    profile: str = PROFILE_NORMAL
    vocabulary: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)
    voice_commands: bool = False
    trailing_space: bool = True


class TextShaper:
    def __init__(self, config: ShapingConfig | None = None):
        self.config = config or ShapingConfig()

    def shape(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        cleaned = self._apply_vocabulary(cleaned)
        if self.config.voice_commands:
            cleaned = self._apply_commands(cleaned)
        cleaned = self._apply_profile(cleaned)
        if self.config.trailing_space and cleaned and not cleaned.endswith(("\n", " ")):
            cleaned += " "
        return cleaned

    # -- passes ------------------------------------------------------------

    def _apply_vocabulary(self, text: str) -> str:
        rules = dict(DEFAULT_REPLACEMENTS)
        rules.update({k.lower(): v for k, v in (self.config.replacements or {}).items()})
        # Longest phrases first so "comfy u i" wins over "ui".
        for spoken in sorted(rules, key=len, reverse=True):
            replacement = rules[spoken]
            text = re.sub(rf"(?<!\w){re.escape(spoken)}(?!\w)", replacement, text,
                          flags=re.IGNORECASE)
        # Bare vocabulary terms: correct casing only, never insert words.
        for term in self.config.vocabulary or []:
            if term:
                text = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", term, text, flags=re.IGNORECASE)
        return text

    def _apply_commands(self, text: str) -> str:
        for spoken in sorted(VOICE_COMMANDS, key=len, reverse=True):
            symbol = VOICE_COMMANDS[spoken]
            text = re.sub(rf"(?<!\w){re.escape(spoken)}(?!\w)\s*", symbol, text,
                          flags=re.IGNORECASE)
        # Punctuation should hug the preceding word.
        return re.sub(r"\s+([.,;:?!])", r"\1", text)

    def _apply_profile(self, text: str) -> str:
        profile = self.config.profile

        if profile == PROFILE_TERMINAL:
            # Literal. Whisper likes to add a sentence full stop and a capital;
            # both are wrong for a shell. "git status" must stay "git status".
            text = text.strip()
            text = re.sub(r"[.]+$", "", text)
            if text[:1].isupper() and not _looks_like_proper_noun(text):
                text = text[0].lower() + text[1:]
            return text

        if profile == PROFILE_DEVELOPER:
            # Keep whisper's sentence casing but do not force a full stop -
            # dictated identifiers and paths should survive untouched.
            return text.strip()

        if profile == PROFILE_CHAT:
            return _capitalise_first(text.strip())

        # Normal prose.
        return _capitalise_first(text.strip())


def _capitalise_first(text: str) -> str:
    if not text:
        return text
    # Only touch ASCII: Bengali has no case, and forcing .upper() on it is a
    # no-op at best and corrupting at worst.
    first = text[0]
    if first.isascii() and first.isalpha() and first.islower():
        return first.upper() + text[1:]
    return text


def _looks_like_proper_noun(text: str) -> bool:
    """Do not lowercase a command that genuinely starts with a known name."""
    first = text.split(" ", 1)[0].strip(".,:;")
    return first in set(DEFAULT_REPLACEMENTS.values())
