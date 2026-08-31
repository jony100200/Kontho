"""Kontho settings: one human-readable JSON file, one place.

Everything the user can change lives here so no component invents its own
storage. Unknown keys from a newer build are preserved on save rather than
dropped, so downgrading does not silently erase configuration.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

APP_NAME = "Kontho"


def app_data_dir() -> Path:
    root = os.environ.get("KONTHO_HOME") or os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(root) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    """Diagnostics only. Dictated text is never written here unless the user
    turns on `log_transcripts` themselves."""
    return app_data_dir() / "kontho.log"


SETTINGS_PATH = app_data_dir() / "settings.json"

# Listening behaviour
MODE_HOLD = "hold"        # push-to-talk
MODE_TOGGLE = "toggle"

# Where finalised text goes
TARGET_DYNAMIC = "dynamic"   # whoever has focus when the phrase finalises
TARGET_LOCKED = "locked"     # whoever had focus when recording started

# Text shaping profiles
PROFILE_NORMAL = "normal"
PROFILE_CHAT = "chat"
PROFILE_DEVELOPER = "developer"
PROFILE_TERMINAL = "terminal"
PROFILES = (PROFILE_NORMAL, PROFILE_CHAT, PROFILE_DEVELOPER, PROFILE_TERMINAL)

# Language modes. "bn+en" is the default because mixed speech is the norm here.
LANG_MIXED = "bn+en"
LANG_BN = "bn"
LANG_EN = "en"
LANG_AUTO = "auto"
LANGUAGES = (LANG_MIXED, LANG_BN, LANG_EN, LANG_AUTO)

DEVICE_CPU = "cpu"
DEVICE_GPU = "gpu"
DEVICE_AUTO = "auto"


def default_threads() -> int:
    """Leave the machine usable.

    Kontho is meant to run beside editors, game engines and local AI work, so
    it takes about half the cores and never the whole box.
    """
    total = os.cpu_count() or 4
    return max(1, min(8, total // 2))


@dataclass
class Settings:
    # General
    start_with_windows: bool = False
    show_floating: bool = True
    hotkey: str = "ctrl+shift+space"
    listen_mode: str = MODE_HOLD

    # Audio
    input_device: str = ""          # substring match; empty = system default
    sample_rate: int = 16000

    # Recognition
    model_id: str = "base-q5_1"
    language: str = LANG_MIXED
    device: str = DEVICE_CPU
    threads: int = field(default_factory=default_threads)
    beam_size: int = 0              # 0 = greedy, cheapest on CPU

    # Typing
    target_mode: str = TARGET_DYNAMIC
    profile: str = PROFILE_NORMAL
    inject_method: str = "auto"     # auto | unicode | clipboard
    unicode_pace_ms: float = 8.0    # gap between typed characters in unicode fallback
    trailing_space: bool = True
    voice_commands: bool = False    # off by default: people dictate these words

    # VAD
    vad_threshold: float = 0.012
    min_speech_ms: int = 200
    silence_ms: int = 350           # phrase finalisation pause (fast responsive cutoff)
    speech_pad_ms: int = 200        # pre-roll so first syllables survive

    # UI
    float_x: int = -1
    float_y: int = -1
    preview_hz: int = 8

    # Vocabulary
    vocabulary: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)

    # Diagnostics
    log_transcripts: bool = False   # privacy: never log dictated text by default

    # Anything a newer build wrote that this one does not know about.
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    # -- persistence -------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or SETTINGS_PATH
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            # A corrupt file must not stop the app from starting.
            return cls()
        known = {f.name for f in fields(cls)} - {"_extra"}
        kwargs = {k: v for k, v in raw.items() if k in known}
        extra = {k: v for k, v in raw.items() if k not in known}
        obj = cls(**kwargs)
        obj._extra = extra
        return obj

    def save(self, path: Path | None = None) -> None:
        path = path or SETTINGS_PATH
        data = {k: v for k, v in asdict(self).items() if k != "_extra"}
        data.update(self._extra)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


class SettingsStore:
    """Thread-safe holder so the UI and the audio thread share one instance."""

    def __init__(self, path: Path | None = None):
        self._path = path or SETTINGS_PATH
        self._lock = threading.RLock()
        self._settings = Settings.load(self._path)

    @property
    def value(self) -> Settings:
        with self._lock:
            return self._settings

    def update(self, **changes: Any) -> Settings:
        with self._lock:
            for key, val in changes.items():
                if hasattr(self._settings, key):
                    setattr(self._settings, key, val)
            self._settings.save(self._path)
            return self._settings

    def save(self) -> None:
        with self._lock:
            self._settings.save(self._path)
