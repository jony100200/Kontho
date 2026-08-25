"""Windows text injection.

This module knows nothing about speech, and the STT side knows nothing about
Word or Terminal. It receives a string and puts it where the caret is.

Primary path is SendInput with KEYEVENTF_UNICODE, which carries Bengali (and
any other script) without depending on the active keyboard layout - a plain
virtual-key approach cannot type বাংলা at all.

Clipboard paste is the fallback: much faster for long text, and the escape
hatch for surfaces that ignore synthetic unicode keys. The previous clipboard
is restored afterwards.
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger("kontho.input")

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56

# Milliseconds between characters when typing directly. 12 ms was the measured
# point where corruption stopped against Notepad; 15 ms keeps a margin.
UNICODE_PACE_MS = 15.0


# `dwExtraInfo` is ULONG_PTR, not a pointer type: 8 bytes on x64, 4 on x86.
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    # All three members must be declared even though only `ki` is ever used.
    # SendInput validates `cbSize` against the real sizeof(INPUT) - 40 bytes on
    # x64, sized by MOUSEINPUT - and returns 0 for anything else. Declaring
    # only KEYBDINPUT yields 32 bytes and every call silently sends 0 events.
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


@dataclass
class InjectResult:
    ok: bool
    method: str
    characters: int = 0
    error: str = ""


class InputBridge:
    """Types text into whatever currently has keyboard focus."""

    def __init__(self, method: str = "auto", pace_ms: float = UNICODE_PACE_MS):
        self.method = method
        self.pace_ms = pace_ms
        self._user32 = ctypes.windll.user32
        self._user32.SendInput.argtypes = (wintypes.UINT, ctypes.c_void_p, ctypes.c_int)
        self._user32.SendInput.restype = wintypes.UINT

    # -- public ------------------------------------------------------------

    def send(self, text: str, *, method: str | None = None) -> InjectResult:
        if not text:
            return InjectResult(True, "noop", 0)
        chosen = method or self.method
        if chosen == "auto":
            chosen = self._auto_method()

        if chosen == "clipboard":
            result = self._send_clipboard(text)
            if result.ok:
                return result
            log.warning("clipboard injection failed (%s); falling back to unicode",
                        result.error)
            return self._send_unicode(text)

        result = self._send_unicode(text)
        if not result.ok:
            log.warning("unicode injection failed (%s); falling back to clipboard",
                        result.error)
            return self._send_clipboard(text)
        return result

    def _auto_method(self) -> str:
        """Clipboard unless using it would destroy something we cannot restore.

        Measured on this box against a real Notepad, verified by reading the
        saved file (2026-08-25):

            clipboard paste          84 ms   correct
            unicode, paced 12 ms    703 ms   correct
            unicode, paced 5 ms     309 ms   CORRUPTED
            unicode, single burst     3 ms   CORRUPTED

        Clipboard is both faster and reliable, so it leads. Its one real cost
        is the clipboard itself: text we save and put back, but an image or a
        copied file cannot be reproduced. Rather than destroy that, we type.
        """
        return "unicode" if _clipboard_holds_unrestorable_data() else "clipboard"

    # -- unicode -----------------------------------------------------------

    def _send_unicode(self, text: str) -> InjectResult:
        """Type character by character, paced.

        Pacing is not politeness, it is correctness. Sending the whole phrase
        in one SendInput call races the target's message pump: the text
        arrives with the right character COUNT but a corrupted tail, e.g.
        "path: D:\\KSAppDev 100% ।।।।।।।।।।।।" instead of the real sentence.
        Measured against Notepad, verified from the saved file, the corruption
        disappears at roughly 12 ms per character; `pace_ms` keeps a margin
        over that and is configurable for slower targets.
        """
        pace = max(0.0, self.pace_ms / 1000.0)
        try:
            sent_chars = 0
            for char in text:
                events: list[_INPUT] = []
                for code in _utf16_units(char):
                    for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                        item = _INPUT()
                        item.type = INPUT_KEYBOARD
                        item.union.ki = _KEYBDINPUT(0, code, flags, 0, 0)
                        events.append(item)

                array = (_INPUT * len(events))(*events)
                sent = self._user32.SendInput(len(events), ctypes.byref(array),
                                              ctypes.sizeof(_INPUT))
                if sent != len(events):
                    # A blocked SendInput is silent unless we ask why. Error 5
                    # means the focused window runs at a higher integrity level
                    # than we do (UIPI), which no retry will fix.
                    code = ctypes.GetLastError()
                    return InjectResult(False, "unicode", sent_chars,
                                        f"SendInput sent {sent}/{len(events)} events "
                                        f"after {sent_chars} chars (GetLastError={code})")
                sent_chars += 1
                if pace:
                    time.sleep(pace)
            return InjectResult(True, "unicode", sent_chars)
        except Exception as exc:
            return InjectResult(False, "unicode", 0, str(exc))

    # -- clipboard ---------------------------------------------------------

    def _send_clipboard(self, text: str) -> InjectResult:
        previous = None
        try:
            import win32clipboard

            # Preserve whatever the user had. Only unicode text is restorable
            # here; for anything else we leave the clipboard rather than
            # destroying data we cannot reproduce.
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                        previous = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                previous = None

            _set_clipboard(text)
            try:
                time.sleep(0.02)      # let the owner change settle
                self._press_ctrl_v()
                time.sleep(0.06)      # let the target read it before restoring
            finally:
                # Restore even when the paste fails. Without this a refused
                # Ctrl+V leaves our dictated text sitting in the user's
                # clipboard, silently destroying whatever they had copied.
                if previous is not None:
                    try:
                        _set_clipboard(previous)
                    except Exception as exc:
                        log.warning("could not restore clipboard: %s", exc)
            return InjectResult(True, "clipboard", len(text))
        except Exception as exc:
            return InjectResult(False, "clipboard", 0, str(exc))

    def _press_ctrl_v(self) -> None:
        """Send the paste accelerator one event at a time.

        Batching the four events into a single SendInput sends them faster
        than the target reads them, and the accelerator is silently dropped -
        measured with Ctrl+S against Notepad, which reported success while the
        document stayed unsaved. 20 ms per event is imperceptible next to the
        60 ms the clipboard hand-off already costs.
        """
        for vk, up in ((VK_CONTROL, False), (VK_V, False), (VK_V, True), (VK_CONTROL, True)):
            item = _INPUT()
            item.type = INPUT_KEYBOARD
            item.union.ki = _KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
            array = (_INPUT * 1)(item)
            sent = self._user32.SendInput(1, ctypes.byref(array), ctypes.sizeof(_INPUT))
            if sent != 1:
                raise OSError(f"Ctrl+V blocked at vk={vk:#x} up={up} "
                              f"(GetLastError={ctypes.GetLastError()})")
            time.sleep(0.02)


def _clipboard_holds_unrestorable_data() -> bool:
    """True when the clipboard holds something we could not put back.

    Text we save and restore. An image, a copied file, or a rich document we
    cannot reproduce, so we must not overwrite it just to insert a phrase.
    """
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return False
            # An empty clipboard has nothing to lose.
            return win32clipboard.EnumClipboardFormats(0) != 0
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        # If we cannot inspect it, assume it matters and type instead.
        return True


def _set_clipboard(text: str) -> None:
    import win32clipboard

    for attempt in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            return
        except Exception:
            # Another process can hold the clipboard for a moment.
            time.sleep(0.05 * (attempt + 1))
    raise IOError("clipboard is locked by another application")


def _utf16_units(char: str) -> list[int]:
    """Characters outside the BMP need a surrogate pair."""
    encoded = char.encode("utf-16-le")
    return [int.from_bytes(encoded[i:i + 2], "little") for i in range(0, len(encoded), 2)]
