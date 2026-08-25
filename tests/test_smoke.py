"""Import-and-construct smoke test.

Runs offscreen so it works over a remote session and in CI. Proves the wiring
holds together; the acceptance tests prove it actually dictates.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

failures: list[str] = []


def check(label: str, fn):
    try:
        result = fn()
        print(f"  ok    {label}" + (f"  -> {result}" if result else ""))
        return result
    except Exception as exc:
        failures.append(f"{label}: {exc}")
        print(f"  FAIL  {label}: {exc}")
        return None


print("-- core --")
from kontho.core.settings import SettingsStore, log_path
from kontho.core.models import ModelRegistry
from kontho.core.controller import Controller, State

settings = check("settings load", lambda: SettingsStore())
registry = check("registry", lambda: ModelRegistry())
check("log path", lambda: log_path().name)
controller = check("controller construct", lambda: Controller(settings, registry))

print("-- startup registration --")
from kontho.core.startup import _launch_command, is_run_at_startup

check("launch command", lambda: _launch_command()[:60] + "…")
check("is registered", lambda: str(is_run_at_startup()))

print("-- benchmark tool --")
from kontho.tools.benchmark import _tone_sample, format_report

check("tone sample", lambda: f"{len(_tone_sample(1.0))} samples")
check("empty report", lambda: format_report([]))

print("-- ui --")
from PySide6.QtWidgets import QApplication

app = check("QApplication", lambda: QApplication.instance() or QApplication([]))

from kontho.ui.overlay import FloatingOverlay
from kontho.ui.tray import KonthoTray
from kontho.ui.settings_window import SettingsWindow
from kontho.ui.benchmark_window import BenchmarkWindow

overlay = check("overlay", lambda: FloatingOverlay(settings))
check("overlay refuses focus", lambda: str(overlay.focusPolicy()))
tray = check("tray", lambda: KonthoTray(settings, registry))
window = check("settings window", lambda: SettingsWindow(settings, registry, controller))
check("benchmark window", lambda: BenchmarkWindow(settings, registry, controller))

print("-- status plumbing --")
from kontho.core.controller import StatusUpdate

check("overlay accepts status",
      lambda: overlay.on_status(StatusUpdate(State.LISTENING, "Listening", "test")) or "emitted")
check("tray accepts status",
      lambda: tray.on_status(StatusUpdate(State.PROCESSING, "Transcribing…")) or "emitted")

print()
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for item in failures:
        print(f"  - {item}")
    raise SystemExit(1)
print("smoke test passed")
