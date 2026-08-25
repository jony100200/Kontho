"""Application shell: wires controller, hotkey, tray and overlay together.

Threading contract:
  * the hotkey listener runs its own Win32 message loop on its own thread
  * the controller's STT worker is a third thread
  * Qt owns only the UI

Everything crossing into Qt goes through a Signal, which Qt queues onto the UI
thread. Touching widgets straight from the hotkey or worker thread is the
classic way to make a tray app crash after ten minutes, so nothing here does it.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from ..core.controller import Controller, State, StatusUpdate
from ..core.hotkey import HotkeyListener
from ..core.models import ModelRegistry
from ..core.settings import SettingsStore
from .overlay import FloatingOverlay
from .settings_window import SettingsWindow
from .tray import KonthoTray

log = logging.getLogger("kontho.app")


class _Bridge(QObject):
    """Marshals worker-thread events onto the Qt thread."""

    status = Signal(object)
    hotkey_press = Signal()
    hotkey_release = Signal()


class KonthoApp:
    def __init__(self, argv: list[str] | None = None):
        self.qt = QApplication(argv or sys.argv)
        self.qt.setApplicationName("Kontho")
        self.qt.setQuitOnLastWindowClosed(False)   # tray app: closing a window is not quitting

        icon_path = Path(__file__).resolve().parents[2] / "Assets" / "Kontho Icon.png"
        self.app_icon = None
        if icon_path.is_file():
            from PySide6.QtGui import QIcon
            self.app_icon = QIcon(str(icon_path))
            self.qt.setWindowIcon(self.app_icon)

        self.settings = SettingsStore()
        self.registry = ModelRegistry()
        self.controller = Controller(self.settings, self.registry)

        self.bridge = _Bridge()
        self.bridge.status.connect(self._on_status, Qt.QueuedConnection)
        self.bridge.hotkey_press.connect(self.controller.on_hotkey_press, Qt.QueuedConnection)
        self.bridge.hotkey_release.connect(self.controller.on_hotkey_release, Qt.QueuedConnection)
        self.controller.subscribe(self.bridge.status.emit)

        self.overlay = FloatingOverlay(self.settings)
        self.tray = KonthoTray(self.settings, self.registry)
        self.settings_window: SettingsWindow | None = None

        self.overlay.clicked.connect(self._open_settings)
        self.tray.start_requested.connect(self.controller.start_listening)
        self.tray.stop_requested.connect(self.controller.stop_listening)
        self.tray.toggle_overlay_requested.connect(self._toggle_overlay)
        self.tray.settings_requested.connect(self._open_settings)
        self.tray.benchmark_requested.connect(self._open_benchmark)
        self.tray.quit_requested.connect(self.quit)

        self.hotkey = HotkeyListener(
            self.settings.value.hotkey,
            on_press=self.bridge.hotkey_press.emit,
            on_release=self.bridge.hotkey_release.emit,
        )

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> int:
        self.tray.show()
        if self.settings.value.show_floating:
            self.overlay.show()

        if not self.hotkey.start():
            # Not fatal - the tray menu and overlay still work.
            self.tray.showMessage(
                "Kontho",
                f"Hotkey unavailable: {self.hotkey.error}\nUse the tray menu, or pick "
                "another combination in Settings.",
                QSystemTrayIcon.Warning,
                6000,
            )
            log.warning("continuing without hotkey: %s", self.hotkey.error)

        self.controller.start()
        cfg = self.settings.value
        self.tray.showMessage(
            "Kontho is running",
            f"Press {cfg.hotkey} anywhere and speak.",
            QSystemTrayIcon.Information,
            4000,
        )
        return self.qt.exec()

    def quit(self) -> None:
        log.info("shutting down")
        try:
            self.hotkey.stop()
            self.controller.shutdown()
        finally:
            self.tray.hide()
            self.qt.quit()

    # -- slots -------------------------------------------------------------

    def _on_status(self, update: StatusUpdate) -> None:
        self.overlay.on_status(update)
        self.tray.on_status(update)
        if update.state is State.NO_TARGET:
            # The one failure the user cannot see from the overlay alone: the
            # text exists but had nowhere to go.
            self.tray.showMessage(
                "Kontho",
                "No editable field had focus, so the text was not inserted.",
                QSystemTrayIcon.Warning,
                4000,
            )

    def _toggle_overlay(self) -> None:
        visible = not self.overlay.isVisible()
        self.overlay.setVisible(visible)
        self.settings.update(show_floating=visible)

    def _open_settings(self) -> None:
        if self.settings_window is None:
            window = SettingsWindow(self.settings, self.registry, self.controller)
            if self.app_icon is not None:
                window.setWindowIcon(self.app_icon)
            window.hotkey_changed.connect(self._rebind_hotkey)
            window.model_changed.connect(self._change_model)
            window.audio_changed.connect(self.controller.apply_audio_settings)
            window.benchmark_requested.connect(self._open_benchmark)
            self.settings_window = window
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _rebind_hotkey(self, combo: str) -> None:
        if self.hotkey.rebind(combo):
            self.tray.showMessage("Kontho", f"Hotkey is now {combo}",
                                  QSystemTrayIcon.Information, 3000)
        else:
            QMessageBox.warning(None, "Kontho",
                                f"Could not register {combo}.\n{self.hotkey.error}")

    def _change_model(self, model_id: str) -> None:
        # load_model blocks while whisper loads; keep the UI honest about it.
        self.controller.load_model(model_id)
        self.tray.refresh_labels()

    def _open_benchmark(self) -> None:
        from .benchmark_window import BenchmarkWindow

        if not hasattr(self, "_bench_window") or self._bench_window is None:
            window = BenchmarkWindow(self.settings, self.registry, self.controller)
            if self.app_icon is not None:
                window.setWindowIcon(self.app_icon)
            self._bench_window = window
        self._bench_window.show()
        self._bench_window.raise_()


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if "--version" in args or "-v" in args:
        print("Kontho 1.0.0 (Universal Local Voice Typing for Windows)")
        return 0

    if "--help" in args or "-h" in args:
        print("Kontho — Universal Local Voice Typing for Windows\n")
        print("Usage: python -m kontho [options]\n")
        print("Options:")
        print("  --tray         Start minimized to the system tray (default)")
        print("  --benchmark    Run the model benchmark tool and exit")
        print("  --cwd <path>   Set the project root directory")
        print("  --version, -v  Show version and exit")
        print("  --help, -h     Show this help and exit")
        return 0

    if "--benchmark" in args:
        from ..tools.benchmark import main as bench_main
        clean_args = [a for a in args if a != "--benchmark"]
        return bench_main(clean_args)

    if "--cwd" in args:
        # Startup registration passes the project root so relative imports work
        # no matter what directory Windows launches us from.
        index = args.index("--cwd")
        if index + 1 < len(args):
            sys.path.insert(0, args[index + 1])

    from ..core.settings import log_path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
        handlers=[
            logging.FileHandler(log_path(), encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    log.info("Kontho starting (python %s)", sys.version.split()[0])

    app = KonthoApp(args)
    return app.run()
