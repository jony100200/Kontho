"""End-to-end insertion proof, verified against the file on disk.

Notepad is opened on a real file; text is sent through the same InputBridge the
dictation pipeline uses; the file is saved and read back. Nothing is trusted:
the assertion is what Windows actually wrote to disk.

Readback deliberately does NOT use WM_GETTEXT. Windows 11 Notepad hosts a
`RichEditD2DPT` control that answers it with a corrupted buffer - during this
work it reported a mangled tail for text that had in fact been inserted
correctly, which would have sent us chasing a bug that was not there.

This is the half of Test 1 that does not depend on the user's voice, and the
whole of Test 7's insertion claim.

    python tests\\test_live_insertion.py

Takes over the keyboard for a few seconds. Do not type while it runs.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kontho.core.input_bridge import (
    _INPUT,
    _KEYBDINPUT,
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    InputBridge,
)

user32 = ctypes.windll.user32
user32.SendInput.argtypes = (wintypes.UINT, ctypes.c_void_p, ctypes.c_int)
user32.SendInput.restype = wintypes.UINT

VK_CONTROL, VK_A, VK_S, VK_DELETE = 0x11, 0x41, 0x53, 0x2E

CASES = [
    ("english", "This is a test of universal voice typing."),
    ("bengali", "আমি বাংলায় কথা বলছি।"),
    ("mixed", "আমি git commit করেছি database এ।"),
    ("symbols", "path: D:\\KSAppDev — 100% done (yes!)"),
    ("long", "The quick brown fox jumps over the lazy dog while the "
             "engineer commits code and pushes it upstream to origin main."),
]


def _key(vk: int, up: bool) -> bool:
    item = _INPUT()
    item.type = INPUT_KEYBOARD
    item.union.ki = _KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    array = (_INPUT * 1)(item)
    return user32.SendInput(1, ctypes.byref(array), ctypes.sizeof(_INPUT)) == 1


def chord(*vks: int) -> bool:
    """Press keys together, release in reverse - one event per call, paced.

    Batching the whole chord into a single SendInput sends it faster than the
    target's message pump reads it, and the accelerator is silently dropped:
    Ctrl+S looked like it fired but Notepad never saved, leaving the window
    title marked dirty. Same race that corrupts batched unicode text.
    """
    ok = True
    for vk in vks:
        ok &= _key(vk, False)
        time.sleep(0.02)
    for vk in reversed(vks):
        ok &= _key(vk, True)
        time.sleep(0.02)
    return ok


def _process_name(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _find_window_by_process(name: str) -> tuple[int, int]:
    """Locate a visible top-level window by process image name.

    Windows 11 ships Notepad as a packaged app: `notepad.exe` is a launcher
    stub and the window belongs to a different process, so searching by the
    PID we spawned finds nothing.
    """
    target = name.lower()
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if _process_name(owner.value) == target and user32.GetWindowTextLengthW(hwnd) > 0:
            found.append((hwnd, owner.value))
            return False
        return True

    user32.EnumWindows(callback, None)
    return found[0] if found else (0, 0)


def _force_foreground(hwnd: int) -> None:
    """Win11 refuses SetForegroundWindow to a background process until the
    foreground lock is released; a synthetic ALT tap does that."""
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)


def main() -> int:
    scratch = Path(tempfile.gettempdir()) / "kontho_insertion_test.txt"
    scratch.write_text("", encoding="utf-8")

    print("Live insertion test - launching Notepad. Do not type until it finishes.\n")
    proc = subprocess.Popen(["notepad.exe", str(scratch)])
    failures = 0
    try:
        time.sleep(2.5)
        top, notepad_pid = _find_window_by_process("notepad.exe")
        if not top:
            print("FAIL: could not find the Notepad window")
            return 1
        _force_foreground(top)
        time.sleep(0.8)

        # Safety gate: this test synthesizes real keystrokes. If Notepad did
        # not take the foreground they would land in whatever the user has
        # open, so refuse to send anything at all.
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(owner))
        if owner.value != notepad_pid:
            print(f"ABORTED: Notepad did not take the foreground (foreground pid "
                  f"{owner.value}, Notepad pid {notepad_pid}).\n"
                  "Refusing to send keystrokes into another application.")
            return 2

        for method in ("clipboard", "unicode", "auto"):
            print(f"method: {method}")
            bridge = InputBridge(method)
            for name, text in CASES:
                chord(VK_CONTROL, VK_A)
                chord(VK_DELETE)
                time.sleep(0.25)

                started = time.perf_counter()
                result = bridge.send(text, method=method)
                elapsed = (time.perf_counter() - started) * 1000
                time.sleep(0.4)
                chord(VK_CONTROL, VK_S)
                time.sleep(1.0)

                got = scratch.read_text(encoding="utf-8").strip()
                landed = got == text
                failures += 0 if landed else 1
                print(f"  {'PASS' if landed else 'FAIL'}  {name:<8} "
                      f"via {result.method:<9} {elapsed:>7.0f}ms")
                if not landed:
                    print(f"        sent {text!r}")
                    print(f"        disk {got!r}")
            print()
    finally:
        try:
            chord(VK_CONTROL, VK_A)
            chord(VK_DELETE)
            time.sleep(0.2)
            chord(VK_CONTROL, VK_S)
            time.sleep(0.6)
            proc.terminate()
        except Exception:
            pass

    total = len(CASES) * 3
    print(f"{total - failures}/{total} insertion cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
