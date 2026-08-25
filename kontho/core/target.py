"""Which window receives the text.

Two modes:
  * dynamic - whatever holds keyboard focus when a phrase finalises
  * locked  - whatever held focus when recording began

Kontho's own windows are never a target. If the overlay were ever focusable it
would swallow the user's dictation, so it is excluded here as well as being
created WS_EX_NOACTIVATE.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("kontho.target")

# Foreground processes that mean "type literally" - no auto punctuation or caps.
TERMINAL_PROCESSES = {
    "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "conhost.exe", "wt.exe", "alacritty.exe", "wezterm-gui.exe", "mintty.exe",
}

DEVELOPER_PROCESSES = {
    "code.exe", "devenv.exe", "rider64.exe", "pycharm64.exe", "idea64.exe",
    "godot.exe", "blender.exe", "sublime_text.exe", "notepad++.exe",
}

CHAT_PROCESSES = {"discord.exe", "slack.exe", "teams.exe", "telegram.exe", "whatsapp.exe"}


@dataclass
class TargetInfo:
    hwnd: int = 0
    title: str = ""
    process: str = ""
    pid: int = 0

    @property
    def valid(self) -> bool:
        return self.hwnd != 0

    @property
    def is_terminal(self) -> bool:
        return self.process.lower() in TERMINAL_PROCESSES

    def suggested_profile(self) -> str:
        name = self.process.lower()
        if name in TERMINAL_PROCESSES:
            return "terminal"
        if name in DEVELOPER_PROCESSES:
            return "developer"
        if name in CHAT_PROCESSES:
            return "chat"
        return "normal"

    def __str__(self) -> str:
        if not self.valid:
            return "no target"
        return f"{self.process} — {self.title[:40]}"


class TargetManager:
    """Tracks the foreground window and remembers a locked one."""

    def __init__(self) -> None:
        self._locked: TargetInfo | None = None
        self._own_pid = os.getpid()

    # -- querying ----------------------------------------------------------

    def foreground(self) -> TargetInfo:
        try:
            import win32gui
            import win32process
        except Exception:
            return TargetInfo()

        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return TargetInfo()
            try:
                title = win32gui.GetWindowText(hwnd) or ""
            except Exception:
                title = ""
            pid = 0
            process = ""
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = _process_name(pid)
            except Exception:
                pass
            if pid == self._own_pid:
                # Kontho's own overlay must never be dictated into.
                return TargetInfo()
            return TargetInfo(hwnd=hwnd, title=title, process=process, pid=pid)
        except Exception as exc:
            log.debug("foreground lookup failed: %s", exc)
            return TargetInfo()

    def has_editable_focus(self) -> bool:
        """Best-effort check that *something* could receive typing.

        Deliberately permissive: Electron, Qt and terminals do not expose a
        classic edit control, and refusing to type into them would break most
        of the applications this tool exists for. A real window that is not
        ours counts as typable.
        """
        return self.foreground().valid

    # -- locking -----------------------------------------------------------

    @property
    def locked(self) -> TargetInfo | None:
        return self._locked

    def lock_current(self) -> TargetInfo:
        self._locked = self.foreground()
        log.info("target locked: %s", self._locked)
        return self._locked

    def unlock(self) -> None:
        self._locked = None
        log.info("target unlocked")

    def resolve(self, mode: str) -> TargetInfo:
        """The window this phrase should go to."""
        if mode == "locked" and self._locked and self._locked.valid:
            if _window_alive(self._locked.hwnd):
                return self._locked
            log.warning("locked target has gone away; falling back to foreground")
            self._locked = None
        return self.foreground()

    def focus(self, target: TargetInfo) -> bool:
        """Bring a locked target forward so injected keys land in it."""
        if not target.valid:
            return False
        try:
            import win32con
            import win32gui

            if win32gui.GetForegroundWindow() == target.hwnd:
                return True
            if win32gui.IsIconic(target.hwnd):
                win32gui.ShowWindow(target.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target.hwnd)
            return True
        except Exception as exc:
            log.debug("could not focus target: %s", exc)
            return False


def _process_name(pid: int) -> str:
    try:
        import win32api
        import win32con
        import win32process

        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid
        )
        try:
            path = win32process.GetModuleFileNameEx(handle, 0)
            return os.path.basename(path)
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def _window_alive(hwnd: int) -> bool:
    try:
        import win32gui

        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False
