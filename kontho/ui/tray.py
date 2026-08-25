"""System tray icon and menu.

The tray is the app's real home: the overlay can be hidden, the settings window
closed, and Kontho keeps listening from here.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..core.controller import State, StatusUpdate

log = logging.getLogger("kontho.tray")

STATE_TINT = {
    State.READY: "#88C0D0",
    State.LISTENING: "#BF616A",
    State.PROCESSING: "#D08770",
    State.INSERTED: "#A3BE8C",
    State.NO_TARGET: "#EBCB8B",
    State.ERROR: "#B48EAD",
    State.LOADING: "#5E81AC",
}


ICON_PATH = Path(__file__).resolve().parents[2] / "Assets" / "Kontho Icon.png"


def _icon(colour: str, state: State = State.READY) -> QIcon:
    """Use the official Kontho Icon with dynamic status badging, or vector fallback."""
    if ICON_PATH.is_file():
        try:
            base = QPixmap(str(ICON_PATH)).scaled(
                32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.drawPixmap(0, 0, base)
            if state != State.READY:
                painter.setBrush(QColor(colour))
                painter.setPen(QColor(28, 32, 40, 220))
                painter.drawEllipse(20, 20, 10, 10)
            painter.end()
            return QIcon(pixmap)
        except Exception as exc:
            log.debug("could not render asset icon: %s", exc)

    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QColor(colour))
    painter.setPen(Qt.NoPen)
    # A microphone-ish capsule: body plus stand.
    painter.drawRoundedRect(QRect(11, 5, 10, 15), 5, 5)
    painter.drawRect(QRect(15, 21, 2, 5))
    painter.drawRoundedRect(QRect(9, 24, 14, 3), 1, 1)
    painter.end()
    return QIcon(pixmap)


class KonthoTray(QSystemTrayIcon):
    start_requested = Signal()
    stop_requested = Signal()
    toggle_overlay_requested = Signal()
    settings_requested = Signal()
    benchmark_requested = Signal()
    quit_requested = Signal()

    def __init__(self, settings_store, registry, parent=None):
        super().__init__(parent)
        self._settings = settings_store
        self._registry = registry
        self.setIcon(_icon(STATE_TINT[State.READY]))
        self.setToolTip("Kontho — Ready")

        menu = QMenu()
        self._act_start = QAction("Start Listening", menu)
        self._act_stop = QAction("Stop Listening", menu)
        self._act_overlay = QAction("Show/Hide Floating Button", menu)
        self._act_settings = QAction("Settings…", menu)
        self._act_bench = QAction("Model Benchmark…", menu)
        self._act_quit = QAction("Quit Kontho", menu)

        self._act_model = QAction("Model: —", menu)
        self._act_model.setEnabled(False)
        self._act_language = QAction("Language: —", menu)
        self._act_language.setEnabled(False)

        self._act_start.triggered.connect(self.start_requested)
        self._act_stop.triggered.connect(self.stop_requested)
        self._act_overlay.triggered.connect(self.toggle_overlay_requested)
        self._act_settings.triggered.connect(self.settings_requested)
        self._act_bench.triggered.connect(self.benchmark_requested)
        self._act_quit.triggered.connect(self.quit_requested)

        menu.addAction(self._act_start)
        menu.addAction(self._act_stop)
        menu.addSeparator()
        menu.addAction(self._act_model)
        menu.addAction(self._act_language)
        menu.addSeparator()
        menu.addAction(self._act_overlay)
        menu.addAction(self._act_settings)
        menu.addAction(self._act_bench)
        menu.addSeparator()
        menu.addAction(self._act_quit)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        self.refresh_labels()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_overlay_requested.emit()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.settings_requested.emit()

    def refresh_labels(self) -> None:
        cfg = self._settings.value
        entry = self._registry.get(cfg.model_id)
        name = entry.display_name if entry else cfg.model_id
        self._act_model.setText(f"Model: {name}")
        self._act_language.setText(f"Language: {cfg.language}")

    def on_status(self, update: StatusUpdate) -> None:
        self.setIcon(_icon(STATE_TINT.get(update.state, "#88C0D0"), state=update.state))
        label = update.state.value.replace("_", " ").title()
        tip = f"Kontho — {label}"
        if update.detail:
            tip += f"\n{update.detail}"
        self.setToolTip(tip[:127])   # Windows truncates beyond this
        listening = update.state is State.LISTENING
        self._act_start.setEnabled(not listening)
        self._act_stop.setEnabled(listening)
