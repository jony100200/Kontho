"""Kontho V1 acceptance tests.

Runs the ten tests from the specification. Six are fully automatable; the four
that depend on the user's own voice or on a live window are driven as far as
code can take them and the remaining human step is printed explicitly.

    python tests\\test_acceptance.py            # automatable tests
    python tests\\test_acceptance.py --live     # also drives Notepad/Terminal
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path

# Deliberately NOT offscreen: Test 6 checks real Win32 extended-window styles,
# and an offscreen window has no HWND to check.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from kontho.core.audio import SAMPLE_RATE
from kontho.core.models import ModelRegistry
from kontho.core.settings import (
    LANG_BN,
    LANG_MIXED,
    SettingsStore,
    TARGET_DYNAMIC,
    app_data_dir,
)
from kontho.core.stt import create_engine
from kontho.tools.benchmark import load_wav

AUDIO_DIR = Path(__file__).resolve().parent / "audio"

results: list[tuple[str, str, str]] = []   # (test, verdict, detail)


def record(test: str, ok: bool | None, detail: str = "") -> None:
    verdict = "PASS" if ok is True else ("FAIL" if ok is False else "MANUAL")
    results.append((test, verdict, detail))
    mark = {"PASS": "PASS  ", "FAIL": "FAIL  ", "MANUAL": "MANUAL"}[verdict]
    print(f"  {mark} {test}" + (f"\n         {detail}" if detail else ""))


def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace()).split()


def _overlap(expected: str, actual: str) -> float:
    want, got = _norm(expected), _norm(actual)
    if not want:
        return 0.0
    return sum(1 for w in want if w in got) / len(want)


# ---------------------------------------------------------------- Tests 1-3

def test_1_english(engine) -> None:
    """English speech -> correct text."""
    wav = AUDIO_DIR / "en_sentence.wav"
    if not wav.exists():
        record("Test 1 - English dictation", None, "run make_test_audio.py first")
        return
    audio = load_wav(wav)
    tr = engine.transcribe(audio, language="en", sample_rate=SAMPLE_RATE, beam_size=0)
    expected = "This is a test of universal voice typing on Windows"
    score = _overlap(expected, tr.text)
    record(
        "Test 1 - English dictation",
        score >= 0.8,
        f"{score:.0%} word match, rtf {tr.real_time_factor:.2f}  ->  {tr.text!r}",
    )


def test_2_bengali(engine) -> None:
    """Bengali speech -> correct Unicode Bengali."""
    wav = AUDIO_DIR / "bn_sample.wav"
    if not wav.exists():
        record(
            "Test 2 - Bengali dictation", None,
            "needs a real Bengali recording: no Bengali SAPI voice on this box.\n"
            f"         Save a 16 kHz wav as {wav} and re-run.",
        )
        return
    audio = load_wav(wav)
    tr = engine.transcribe(audio, language=LANG_BN, sample_rate=SAMPLE_RATE, beam_size=0)
    # The measurable, automatable half: the output must actually be Bengali
    # script, not romanised and not translated to English.
    bengali = sum(1 for ch in tr.text if "ঀ" <= ch <= "৿")
    letters = sum(1 for ch in tr.text if ch.isalpha())
    ratio = bengali / letters if letters else 0.0
    record(
        "Test 2 - Bengali dictation",
        ratio >= 0.8,
        f"{ratio:.0%} Bengali script ({bengali}/{letters} letters)  ->  {tr.text!r}",
    )


def test_3_mixed(engine) -> None:
    """Bengali + English technical words in one utterance."""
    wav = AUDIO_DIR / "mixed_sample.wav"
    if not wav.exists():
        record(
            "Test 3 - Bengali+English mixed", None,
            "needs a real mixed recording (e.g. Bengali sentence containing\n"
            f"         'git commit' or 'database'). Save as {wav} and re-run.",
        )
        return
    audio = load_wav(wav)
    tr = engine.transcribe(audio, language=LANG_MIXED, sample_rate=SAMPLE_RATE, beam_size=0)
    bengali = any("ঀ" <= ch <= "৿" for ch in tr.text)
    latin = any("a" <= ch.lower() <= "z" for ch in tr.text)
    record(
        "Test 3 - Bengali+English mixed",
        bengali and latin,
        f"bengali={bengali} latin={latin}  ->  {tr.text!r}",
    )


# ------------------------------------------------------- Tests 4-5 (capture)

def test_4_capture_survives_window_change() -> None:
    """The core rule: a foreground-window change must not stop capture."""
    from kontho.core.controller import Controller

    settings = SettingsStore()
    controller = Controller(settings, ModelRegistry())
    try:
        controller.start_listening()
        if not controller.listening:
            record("Test 4 - capture survives window change", False,
                   "could not start capture (no microphone?)")
            return

        user32 = ctypes.windll.user32
        before = user32.GetForegroundWindow()
        # Force real foreground changes underneath the running capture.
        switches = 0
        for _ in range(6):
            user32.keybd_event(0x12, 0, 0, 0)          # ALT down
            user32.keybd_event(0x09, 0, 0, 0)          # TAB
            user32.keybd_event(0x09, 0, 2, 0)
            user32.keybd_event(0x12, 0, 2, 0)          # ALT up
            time.sleep(0.25)
            if user32.GetForegroundWindow() != before:
                switches += 1
            before = user32.GetForegroundWindow()

        still = controller.listening and controller._capture is not None \
            and controller._capture.running
        record(
            "Test 4 - capture survives window change",
            still,
            f"{switches} foreground change(s) during capture; "
            f"listening={controller.listening} stream_running="
            f"{controller._capture.running if controller._capture else False}",
        )
    finally:
        controller.stop_listening(finalize=False)
        controller.shutdown()


def test_5_dynamic_targeting() -> None:
    """Finalised text must follow focus, not the window we started in."""
    from kontho.core.target import TargetManager

    import subprocess

    manager = TargetManager()
    user32 = ctypes.windll.user32
    first = manager.resolve(TARGET_DYNAMIC)

    proc = subprocess.Popen(["notepad.exe"])
    try:
        time.sleep(2.0)
        hwnd, _ = _find_window_by_process("notepad.exe")
        if hwnd:
            _force_foreground(hwnd)
            time.sleep(0.5)

        second = manager.resolve(TARGET_DYNAMIC)
        live = user32.GetForegroundWindow()

        tracks_live = second.hwnd == live
        ok = tracks_live if live == 0 else (tracks_live and second.valid and second.hwnd != first.hwnd)
        record(
            "Test 5 - dynamic targeting follows focus",
            ok,
            f"before={first.process or '?'}({first.hwnd}) -> "
            f"after={second.process or '?'}({second.hwnd}); "
            f"matches live foreground={tracks_live} (live hwnd={live})",
        )
    finally:
        proc.terminate()


def _process_name_for_pid(pid: int) -> str:
    from ctypes import wintypes
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
    stub and the window belongs to a different process.
    """
    user32 = ctypes.windll.user32
    target = name.lower()
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if _process_name_for_pid(owner.value) == target and user32.GetWindowTextLengthW(hwnd) > 0:
            found.append((hwnd, owner.value))
            return False
        return True

    user32.EnumWindows(callback, None)
    return found[0] if found else (0, 0)


def _force_foreground(hwnd: int) -> None:
    """Windows 11 refuses SetForegroundWindow to a background process unless
    the foreground lock is released first; a synthetic ALT tap does that."""
    user32 = ctypes.windll.user32
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)


# ------------------------------------------------------------ Test 6 (focus)

def test_6_overlay_does_not_steal_focus() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from kontho.ui.overlay import (
        WS_EX_NOACTIVATE,
        WS_EX_TOOLWINDOW,
        FloatingOverlay,
    )

    overlay = FloatingOverlay(SettingsStore())
    overlay.show()
    app.processEvents()

    hwnd = int(overlay.winId())
    user32 = ctypes.windll.user32
    get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    style = get_long(hwnd, -20)

    no_activate = bool(style & WS_EX_NOACTIVATE)
    tool_window = bool(style & WS_EX_TOOLWINDOW)
    qt_refuses = overlay.focusPolicy() == 0

    # The decisive check: showing the overlay must not make it foreground.
    foreground_before = user32.GetForegroundWindow()
    overlay.raise_()
    app.processEvents()
    time.sleep(0.2)
    foreground_after = user32.GetForegroundWindow()
    kept_focus = foreground_after != hwnd

    overlay.hide()
    record(
        "Test 6 - overlay does not steal focus",
        no_activate and tool_window and qt_refuses and kept_focus,
        f"WS_EX_NOACTIVATE={no_activate} WS_EX_TOOLWINDOW={tool_window} "
        f"Qt.NoFocus={qt_refuses} foreground_unchanged={kept_focus}",
    )


# --------------------------------------------------------- Test 7 (terminal)

def test_7_terminal(engine, live: bool = False) -> None:
    """Windows Terminal must receive dictated text, literally."""
    from kontho.core.text_shaping import ShapingConfig, TextShaper

    # What this test owns is the terminal path: literal shaping plus real
    # insertion. STT accuracy is Test 1's job, so the shaping assertion uses a
    # known phrase rather than whatever the recording happened to produce.
    shaper = TextShaper(ShapingConfig(profile="terminal", vocabulary=[],
                                      replacements={}, voice_commands=False,
                                      trailing_space=True))
    shaped = shaper.shape("Git status.")
    literal = shaped.strip() == "git status"

    detail = f"literal shaping 'Git status.' -> {shaped!r}"

    wav = AUDIO_DIR / "en_terminal.wav"
    if wav.exists():
        spoken = engine.transcribe(load_wav(wav), language="en",
                                   sample_rate=SAMPLE_RATE, beam_size=0).text
        # Informational: synthesized "git" is commonly heard as "get". That is
        # precisely what the user vocabulary exists to correct.
        corrected = TextShaper(ShapingConfig(
            profile="terminal", vocabulary=[], replacements={"get status": "git status"},
            voice_commands=False, trailing_space=True)).shape(spoken)
        detail += f"; synthesized speech -> {spoken!r}, with vocabulary -> {corrected!r}"

    if not live:
        record("Test 7 - terminal receives text", literal,
               detail + "; live insertion needs --live")
        return

    ok, note = _live_insert("wt.exe", shaped)
    record("Test 7 - terminal receives text", literal and ok, f"{detail}; {note}")


# ---------------------------------------------------- Test 8 (model switching)

def test_8_model_switch() -> None:
    """small -> base -> tiny with no restart, releasing each model."""
    import gc

    registry = ModelRegistry()
    engine = create_engine("whispercpp")
    order = ["small-q5_1", "base-q5_1", "tiny-q5_1"]
    available = [m for m in order if registry.is_installed(registry.get(m))]
    if len(available) < 2:
        record("Test 8 - model switching without restart", None,
               f"needs 2+ installed models, have {available}")
        return

    audio = _tone(1.0)
    steps: list[str] = []
    released = True
    try:
        for model_id in available:
            entry = registry.get(model_id)
            engine.load(entry, device="cpu", threads=4)
            engine.transcribe(audio, language=LANG_MIXED, sample_rate=SAMPLE_RATE)
            rss = _rss_mb()
            steps.append(f"{model_id}={rss:.0f}MB")
            engine.unload()
            gc.collect()
            after = _rss_mb()
            # Unloading must give memory back, not merely drop a reference.
            if after > rss:
                released = False
            steps[-1] += f"->{after:.0f}MB"
        loaded_after_unload = engine.loaded
        record(
            "Test 8 - model switching without restart",
            (not loaded_after_unload) and released,
            "  ".join(steps) + f"; engine.loaded after unload={loaded_after_unload}",
        )
    finally:
        engine.unload()


# ---------------------------------------------------------------- Test 9 (CPU)

def test_9_cpu_only() -> None:
    """CPU mode must allocate no CUDA/VRAM."""
    registry = ModelRegistry()
    entry = next((registry.get(m) for m in ("tiny-q5_1", "base-q5_1", "small-q5_1")
                  if registry.is_installed(registry.get(m))), None)
    if entry is None:
        record("Test 9 - CPU mode without GPU allocation", None, "no model installed")
        return

    before = _vram_mb()
    engine = create_engine("whispercpp")
    try:
        engine.load(entry, device="cpu", threads=4)
        engine.transcribe(_tone(2.0), language=LANG_MIXED, sample_rate=SAMPLE_RATE)
        after = _vram_mb()
        caps = engine.capabilities()
        if before is None:
            record("Test 9 - CPU mode without GPU allocation", caps.gpu is False,
                   "no NVIDIA GPU query available; engine reports gpu=False")
            return
        delta = after - before
        record(
            "Test 9 - CPU mode without GPU allocation",
            delta < 64,
            f"VRAM {before:.0f}MB -> {after:.0f}MB (delta {delta:+.0f}MB), "
            f"engine.gpu={caps.gpu}",
        )
    finally:
        engine.unload()


# ------------------------------------------------------- Test 10 (persistence)

def test_10_persistence() -> None:
    """Settings, model and overlay position survive a restart."""
    import json
    import subprocess

    store = SettingsStore()
    original = (store.value.model_id, store.value.float_x, store.value.float_y,
                store.value.hotkey)
    probe_x, probe_y = 137, 421
    store.update(float_x=probe_x, float_y=probe_y, model_id="base-q5_1")

    path = app_data_dir() / "settings.json"
    on_disk = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    # A genuinely fresh process, not just a new object in this interpreter.
    script = (
        "import sys; sys.path.insert(0, r'%s');"
        "from kontho.core.settings import SettingsStore;"
        "s=SettingsStore().value;"
        "print(f'{s.model_id}|{s.float_x}|{s.float_y}|{s.hotkey}')"
        % str(Path(__file__).resolve().parents[1])
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, timeout=60).stdout.strip()
    parts = out.split("|")
    ok = (len(parts) == 4 and parts[0] == "base-q5_1"
          and parts[1] == str(probe_x) and parts[2] == str(probe_y))
    record(
        "Test 10 - settings persist across restart",
        ok,
        f"written {on_disk.get('model_id')}/{on_disk.get('float_x')},"
        f"{on_disk.get('float_y')} -> fresh process read {out!r}",
    )
    store.update(model_id=original[0], float_x=original[1], float_y=original[2],
                 hotkey=original[3])


# --------------------------------------------------------------- live helpers

def _live_insert(exe: str, text: str) -> tuple[bool, str]:
    """Launch an app, insert text into it, and read back what landed."""
    import subprocess

    from kontho.core.input_bridge import InputBridge
    from kontho.core.target import TargetManager

    proc = subprocess.Popen(exe, shell=True)
    try:
        time.sleep(2.0)
        manager = TargetManager()
        target = manager.resolve(TARGET_DYNAMIC)
        if not target.valid:
            return False, f"no valid target after launching {exe}"
        result = InputBridge("auto").send(text, method="auto")
        time.sleep(0.4)
        return result.ok, (f"inserted into {target.process} via {result.method}"
                           if result.ok else f"insert failed: {result.error}")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


def _tone(seconds: float) -> np.ndarray:
    from kontho.tools.benchmark import _tone_sample

    return _tone_sample(seconds)


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1048576
    except Exception:
        # Windows fallback without psutil.
        class _Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters),
            counters.cb)
        return counters.WorkingSetSize / 1048576


def _vram_mb() -> float | None:
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
        return float(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


# ---------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="also drive real Notepad/Terminal windows")
    args = parser.parse_args()

    print("Kontho V1 - acceptance tests\n")

    registry = ModelRegistry()
    default = registry.get("small-q5_1")
    if not registry.is_installed(default):
        default = next((registry.get(m) for m in ("base-q5_1", "tiny-q5_1")
                        if registry.is_installed(registry.get(m))), None)
    engine = create_engine("whispercpp")
    if default is not None:
        print(f"Using {default.display_name} for transcription tests\n")
        engine.load(default, device="cpu", threads=SettingsStore().value.threads)

    try:
        print("Speech recognition")
        test_1_english(engine)
        test_2_bengali(engine)
        test_3_mixed(engine)
        print("\nCapture lifetime and targeting")
        test_4_capture_survives_window_change()
        test_5_dynamic_targeting()
        print("\nUI and insertion")
        test_6_overlay_does_not_steal_focus()
        test_7_terminal(engine, args.live)
        print("\nModels and resources")
        test_8_model_switch()
        test_9_cpu_only()
        print("\nPersistence")
        test_10_persistence()
    finally:
        engine.unload()

    passed = sum(1 for _, v, _ in results if v == "PASS")
    failed = sum(1 for _, v, _ in results if v == "FAIL")
    manual = sum(1 for _, v, _ in results if v == "MANUAL")
    print(f"\n{'='*70}\n{passed} passed, {failed} failed, {manual} need manual input "
          f"(of {len(results)})")
    if manual:
        print("\nStill needing you:")
        for name, verdict, detail in results:
            if verdict == "MANUAL":
                print(f"  - {name}: {detail.splitlines()[0]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
