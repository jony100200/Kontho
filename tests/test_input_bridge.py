"""InputBridge unit tests - no keystrokes are sent anywhere.

SendInput is stubbed, so this is safe to run while someone is using the
machine. It proves the parts that were actually broken:

  * the INPUT struct is the size Windows validates against
  * every character reaches SendInput, in order, as a keydown/keyup pair
  * Bengali and astral characters are encoded as correct UTF-16 units
  * `auto` protects a clipboard holding data it could not restore
  * a refused SendInput is reported, never silently swallowed

The live end-to-end proof is tests/test_live_insertion.py, which does take
over the keyboard.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kontho.core import input_bridge as ib

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}" + (f"  ({detail})" if detail else ""))
    else:
        failures.append(f"{label}: {detail}")
        print(f"  FAIL  {label}  ({detail})")


class _FakeSendInput:
    """Records events instead of injecting them."""

    def __init__(self, accept: bool = True):
        self.accept = accept
        self.calls = 0
        self.events: list[tuple[int, int, int]] = []   # (wVk, wScan, dwFlags)
        self.argtypes = None
        self.restype = None

    def __call__(self, count, array, size):
        self.calls += 1
        if size != ctypes.sizeof(ib._INPUT):
            raise AssertionError(f"wrong cbSize {size}")
        if not self.accept:
            return 0
        items = ctypes.cast(array, ctypes.POINTER(ib._INPUT * count)).contents
        for item in items:
            self.events.append((item.union.ki.wVk, item.union.ki.wScan,
                                item.union.ki.dwFlags))
        return count


class _FakeUser32:
    """Stands in for windll.user32 so nothing reaches the real input queue."""

    def __init__(self, accept: bool = True):
        self.SendInput = _FakeSendInput(accept)


def _bridge(accept: bool = True) -> tuple[ib.InputBridge, _FakeSendInput]:
    bridge = ib.InputBridge("unicode", pace_ms=0.0)
    fake = _FakeUser32(accept)
    bridge._user32 = fake                      # type: ignore[assignment]
    # The clipboard fallback would touch the real clipboard and the real
    # keyboard. This file must stay safe to run while someone is working, so
    # the fallback is disabled outright rather than merely discouraged.
    bridge._send_clipboard = lambda text: ib.InjectResult(   # type: ignore[assignment]
        False, "clipboard", 0, "clipboard disabled in unit test")
    return bridge, fake.SendInput


print("-- struct layout --")
check("sizeof(INPUT) is 40 on x64", ctypes.sizeof(ib._INPUT) == 40,
      f"got {ctypes.sizeof(ib._INPUT)}")
check("union sized by MOUSEINPUT",
      ctypes.sizeof(ib._MOUSEINPUT) >= ctypes.sizeof(ib._KEYBDINPUT),
      f"mouse={ctypes.sizeof(ib._MOUSEINPUT)} kbd={ctypes.sizeof(ib._KEYBDINPUT)}")

print("\n-- utf-16 encoding --")
check("ascii is one unit", ib._utf16_units("A") == [0x41], str(ib._utf16_units("A")))
check("bengali is one unit", ib._utf16_units("আ") == [0x0986], str(ib._utf16_units("আ")))
check("astral char is a surrogate pair", len(ib._utf16_units("𝄞")) == 2,
      str(ib._utf16_units("𝄞")))

print("\n-- unicode injection --")
bridge, fake = _bridge()
result = bridge.send("Hi আ", method="unicode")
check("reports success", result.ok and result.method == "unicode", str(result))
check("counts every character", result.characters == 4, str(result.characters))
check("one call per character", fake.calls == 4, f"{fake.calls} calls")
check("keydown+keyup per unit", len(fake.events) == 8, f"{len(fake.events)} events")
scans = [scan for vk, scan, flags in fake.events if not flags & ib.KEYEVENTF_KEYUP]
check("characters arrive in order", scans == [0x48, 0x69, 0x20, 0x0986], str(scans))
check("wVk is 0 for unicode events", all(vk == 0 for vk, _, _ in fake.events))
check("KEYEVENTF_UNICODE set on all",
      all(flags & ib.KEYEVENTF_UNICODE for _, _, flags in fake.events))

print("\n-- refusal is reported, not swallowed --")
bridge, fake = _bridge(accept=False)
result = bridge._send_unicode("abc")
check("failure reported", result.ok is False, str(result.ok))
check("error names SendInput and GetLastError",
      "SendInput" in result.error and "GetLastError" in result.error, result.error)
check("reports how far it got", "0 chars" in result.error, result.error)

print("\n-- pacing --")
import time as _time

bridge, fake = _bridge()
bridge.pace_ms = 5.0
started = _time.perf_counter()
bridge.send("abcdef", method="unicode")
elapsed = (_time.perf_counter() - started) * 1000
check("pace is applied between characters", elapsed >= 25, f"{elapsed:.0f}ms for 6 chars")
check("default pace clears the responsive threshold", ib.UNICODE_PACE_MS >= 5.0,
      f"{ib.UNICODE_PACE_MS}ms")

print("\n-- auto method protects the clipboard --")
original = ib._clipboard_holds_unrestorable_data
try:
    ib._clipboard_holds_unrestorable_data = lambda: False
    check("text clipboard -> clipboard paste",
          ib.InputBridge("auto")._auto_method() == "clipboard")
    ib._clipboard_holds_unrestorable_data = lambda: True
    check("image/file clipboard -> types instead",
          ib.InputBridge("auto")._auto_method() == "unicode")
finally:
    ib._clipboard_holds_unrestorable_data = original

print("\n-- empty input --")
bridge, fake = _bridge()
result = bridge.send("", method="unicode")
check("empty text is a no-op", result.ok and fake.calls == 0, str(result))

print()
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for item in failures:
        print(f"  - {item}")
    raise SystemExit(1)
print("input bridge tests passed")
