"""System-wide hotkey via RegisterHotKey on a dedicated thread.

Win32 delivers WM_HOTKEY to the thread that registered it, so this owns its own
message loop and never touches the UI thread. Nothing about the combination is
hard-coded: it is parsed from a string like "ctrl+shift+space".

Press and release are reported separately so one binding serves both
push-to-talk and toggle. RegisterHotKey has no release event, so the release is
detected by polling the key's physical state while it is held - cheap, and only
while the key is actually down.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("kontho.hotkey")

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_MODS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "alt": MOD_ALT,
    "win": MOD_WIN, "super": MOD_WIN, "cmd": MOD_WIN,
}

# Virtual-key codes for the names people actually type in a settings box.
_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "insert": 0x2D,
    "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "pause": 0x13, "scrolllock": 0x91,
    # Symbols and punctuation
    "grave": 0xC0, "backtick": 0xC0, "tilde": 0xC0, "`": 0xC0, "~": 0xC0,
    "minus": 0xBD, "hyphen": 0xBD, "dash": 0xBD, "-": 0xBD,
    "equal": 0xBB, "equals": 0xBB, "plus": 0xBB, "=": 0xBB, "+": 0xBB,
    "bracketleft": 0xDB, "openbracket": 0xDB, "[": 0xDB, "{": 0xDB,
    "bracketright": 0xDD, "closebracket": 0xDD, "]": 0xDD, "}": 0xDD,
    "backslash": 0xDC, "\\": 0xDC, "|": 0xDC,
    "semicolon": 0xBA, ";": 0xBA, ":": 0xBA,
    "quote": 0xDE, "apostrophe": 0xDE, "'": 0xDE, '"': 0xDE,
    "comma": 0xBC, "<": 0xBC, ",": 0xBC,
    "period": 0xBE, "dot": 0xBE, ">": 0xBE, ".": 0xBE,
    "slash": 0xBF, "/": 0xBF, "?": 0xBF,
}
for _i in range(1, 25):
    _KEYS[f"f{_i}"] = 0x6F + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    _KEYS[_c] = ord(_c.upper())
for _d in "0123456789":
    _KEYS[_d] = ord(_d)


@dataclass
class HotkeyCombo:
    modifiers: int
    vk: int
    label: str

    @property
    def valid(self) -> bool:
        return self.vk != 0


def parse_hotkey(text: str) -> HotkeyCombo:
    """"ctrl+shift+space" -> modifiers + virtual key."""
    raw = str(text or "").strip().lower()
    # Handle literal trailing "+" if entered as "ctrl++"
    if raw.endswith("++"):
        raw_parts = raw[:-2].split("+") + ["+"]
    else:
        raw_parts = raw.split("+")

    parts = [p.strip() for p in raw_parts if p.strip()]
    mods = 0
    vk = 0
    for part in parts:
        if part in _MODS:
            mods |= _MODS[part]
        elif part in _KEYS:
            vk = _KEYS[part]
    return HotkeyCombo(mods | MOD_NOREPEAT, vk, text)


class HotkeyListener:
    """Registers one combo and reports press/release."""

    HOTKEY_ID = 0xB001

    def __init__(self, combo: str, on_press: Callable[[], None],
                 on_release: Callable[[], None] | None = None):
        self._combo = parse_hotkey(combo)
        self._on_press = on_press
        self._on_release = on_release
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._stop = threading.Event()
        self._registered = False
        self.error = ""

    @property
    def registered(self) -> bool:
        return self._registered

    def start(self) -> bool:
        if not self._combo.valid:
            self.error = f"unrecognised hotkey: {self._combo.label}"
            log.error(self.error)
            return False
        self._stop.clear()
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True,
                                        name="kontho-hotkey")
        self._thread.start()
        ready.wait(timeout=3.0)
        return self._registered

    def stop(self) -> None:
        self._stop.set()
        if self._thread_id:
            try:
                import ctypes

                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._registered = False

    def rebind(self, combo: str) -> bool:
        self.stop()
        self._combo = parse_hotkey(combo)
        return self.start()

    def _run(self, ready: threading.Event) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(None, self.HOTKEY_ID, self._combo.modifiers, self._combo.vk):
            # Almost always means another application already owns the combo.
            self.error = f"could not register {self._combo.label} (in use by another app?)"
            log.error(self.error)
            ready.set()
            return

        self._registered = True
        self.error = ""
        log.info("hotkey registered: %s", self._combo.label)
        ready.set()

        msg = wintypes.MSG()
        try:
            while not self._stop.is_set():
                got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got in (0, -1):
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    self._fire()
        finally:
            user32.UnregisterHotKey(None, self.HOTKEY_ID)
            self._registered = False
            log.info("hotkey released: %s", self._combo.label)

    def _fire(self) -> None:
        try:
            self._on_press()
        except Exception as exc:
            log.error("hotkey press handler raised: %s", exc)
        if self._on_release is None:
            return
        # RegisterHotKey gives no key-up, so watch the physical key while held.
        threading.Thread(target=self._await_release, daemon=True,
                         name="kontho-hotkey-release").start()

    def _await_release(self) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        while not self._stop.is_set():
            if not (user32.GetAsyncKeyState(self._combo.vk) & 0x8000):
                break
            time.sleep(0.02)
        try:
            if self._on_release:
                self._on_release()
        except Exception as exc:
            log.error("hotkey release handler raised: %s", exc)
