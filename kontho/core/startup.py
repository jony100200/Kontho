"""Run-at-login registration.

Uses the per-user Run key rather than a scheduled task or a Startup-folder
shortcut: no elevation, no COM, and trivially reversible.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger("kontho.startup")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Kontho"


def _launch_command() -> str:
    """The command Windows should run at login.

    Frozen: the exe itself. Source: pythonw.exe (no console window) running
    the package, quoted because these paths contain spaces.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    interpreter = windowless if windowless.exists() else exe
    project_root = Path(__file__).resolve().parents[2]
    return f'"{interpreter}" -m kontho --tray --cwd "{project_root}"'


def set_run_at_startup(enabled: bool) -> tuple[bool, str]:
    try:
        import winreg
    except ImportError:
        return False, "winreg unavailable (not Windows)"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
                log.info("registered for startup")
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                    log.info("unregistered from startup")
                except FileNotFoundError:
                    pass  # Already absent: the requested end state.
        return True, ""
    except OSError as exc:
        log.error("startup registration failed: %s", exc)
        return False, str(exc)


def is_run_at_startup() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except (ImportError, FileNotFoundError, OSError):
        return False
