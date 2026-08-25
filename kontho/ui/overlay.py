"""The floating control.

The single most important property: this window must never take keyboard
focus. If it did, the user's dictation would land in Kontho instead of Word,
which defeats the whole product.

That is enforced twice over:
  * Qt.WindowDoesNotAcceptFocus / WA_ShowWithoutActivating at the Qt level
  * WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW at the Win32 level, applied after the
    native handle exists because Qt overwrites the style on creation

WS_EX_TOOLWINDOW also keeps it out of Alt+Tab, which is what the spec asks for.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from ..core.controller import State, StatusUpdate

log = logging.getLogger("kontho.overlay")

WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
GWL_EXSTYLE = -20

STATE_COLOURS = {
    State.READY: ("#00D2FF", "#D8DEE9", "Ready"),
    State.LISTENING: ("#FF4B5C", "#FFFFFF", "Listening"),
    State.PROCESSING: ("#FFB703", "#FFFFFF", "Working"),
    State.INSERTED: ("#10B981", "#2E3440", "Inserted"),
    State.NO_TARGET: ("#EBCB8B", "#2E3440", "No target"),
    State.ERROR: ("#EF4444", "#FFFFFF", "Error"),
    State.LOADING: ("#6366F1", "#FFFFFF", "Loading"),
}


class AudioHeartbeatWidget(QWidget):
    """Animated 4-bar dynamic audio equalizer / heartbeat wave.

    Bounces in real-time to speech volume during LISTENING,
    shows wave pulses during PROCESSING, and resting soft pulse when READY.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(22, 16)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._volume = 0.0
        self._state = State.READY
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)  # ~33 FPS smooth wave
        self._timer.timeout.connect(self._on_tick)

    def set_state(self, state: State, volume: float = 0.0) -> None:
        self._state = state
        self._volume = max(0.0, min(1.0, volume))
        if state in (State.LISTENING, State.PROCESSING) and not self._timer.isActive():
            self._timer.start()
        elif state not in (State.LISTENING, State.PROCESSING) and self._timer.isActive():
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _on_tick(self) -> None:
        self._phase += 0.25
        if self._phase > 6.283:
            self._phase -= 6.283
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        if self._state is State.LISTENING:
            color = QColor(255, 75, 92) if self._volume > 0.04 else QColor(220, 90, 105)
        elif self._state is State.PROCESSING:
            color = QColor(255, 183, 3)
        elif self._state is State.INSERTED:
            color = QColor(16, 185, 129)
        elif self._state in (State.ERROR, State.NO_TARGET):
            color = QColor(239, 68, 68)
        elif self._state is State.LOADING:
            color = QColor(99, 102, 241)
        else:
            color = QColor(0, 210, 255)

        painter.setBrush(color)

        bar_w = 3.0
        gap = 2.0
        max_h = 14.0
        min_h = 3.0
        mid_y = 8.0

        offsets = [0.4, 1.0, 0.8, 0.5]
        for i in range(4):
            x = i * (bar_w + gap) + 1.0
            if self._state is State.LISTENING:
                amp = max(0.18, min(1.0, self._volume * 1.5 * offsets[i]))
                h = min_h + (max_h - min_h) * amp
            elif self._state is State.PROCESSING:
                wave = (math.sin(self._phase + i * 0.8) + 1.0) / 2.0
                h = min_h + (max_h - min_h) * (0.25 + 0.75 * wave)
            elif self._state is State.INSERTED:
                h = max_h * 0.85
            else:
                h = min_h + 1.0

            y = mid_y - h / 2.0
            painter.drawRoundedRect(QRectF(x, y, bar_w, h), 1.5, 1.5)


class FloatingOverlay(QWidget):
    """Small always-on-top pill that shows state, audio heartbeat, and live preview."""

    clicked = Signal()

    def __init__(self, settings_store):
        super().__init__(None)
        self._settings = settings_store
        self._drag_origin: QPoint | None = None
        self._state = State.READY
        self._volume = 0.0
        self._applied_native_style = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                        # keeps it off the taskbar
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 14, 6)
        layout.setSpacing(8)

        icon_path = Path(__file__).resolve().parents[2] / "Assets" / "Kontho Icon.png"
        if icon_path.is_file():
            self._icon_lbl = QLabel()
            pix = QPixmap(str(icon_path)).scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._icon_lbl.setPixmap(pix)
            layout.addWidget(self._icon_lbl)

        self._heartbeat = AudioHeartbeatWidget(self)
        self._label = QLabel("Kontho")
        self._label.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self._preview = QLabel("")
        self._preview.setFont(QFont("Segoe UI", 9))
        self._preview.setMaximumWidth(420)
        self._preview.hide()

        layout.addWidget(self._heartbeat)
        layout.addWidget(self._label)
        layout.addWidget(self._preview)

        self._restore_position()
        self._paint_state(State.READY, "")

    # -- Win32 hardening ---------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._applied_native_style:
            self._apply_native_style()
            self._applied_native_style = True

    def _apply_native_style(self) -> None:
        """Qt sets its own extended style at creation; ours must go on after."""
        try:
            import ctypes

            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            current = get_long(hwnd, GWL_EXSTYLE)
            set_long(hwnd, GWL_EXSTYLE,
                     current | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
            log.info("overlay hwnd=%s marked NOACTIVATE|TOOLWINDOW|TOPMOST", hwnd)
        except Exception as exc:
            # Non-fatal: Qt's own flags already refuse focus in most cases.
            log.warning("could not apply native window style: %s", exc)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        rect = self.rect().adjusted(0, 0, -1, -1)
        path.addRoundedRect(rect, 14, 14)
        painter.fillPath(path, QColor(18, 19, 22, 240))

        # Highlight border when audio is actively being detected
        vol = getattr(self, "_volume", 0.0)
        if self._state is State.LISTENING and vol > 0.08:
            painter.strokePath(path, QColor(239, 68, 68, 230))
        elif self._state is State.LISTENING:
            painter.strokePath(path, QColor(191, 97, 106, 180))
        else:
            painter.strokePath(path, QColor(46, 51, 66, 220))

    def _paint_state(self, state: State, detail: str) -> None:
        colour, text_colour, label = STATE_COLOURS.get(state, STATE_COLOURS[State.READY])
        vol = getattr(self, "_volume", 0.0)
        self._heartbeat.set_state(state, vol)

        self._label.setStyleSheet("color: #E5E9F0;")
        self._label.setText(label if not detail else f"{label} · {detail}"[:52])
        self._preview.setStyleSheet("color: #9AA5B4;")
        self.adjustSize()

    # -- controller feed ---------------------------------------------------

    def on_status(self, update: StatusUpdate) -> None:
        self._state = update.state
        self._volume = getattr(update, "volume", 0.0)
        self._paint_state(update.state, update.detail)
        if update.state is State.LISTENING and update.preview:
            self._preview.setText(update.preview[-70:])
            self._preview.show()
        elif update.state is not State.LISTENING:
            self._preview.hide()
        self.adjustSize()
        self.update()

    # -- dragging ----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_origin is not None:
            self._drag_origin = None
            self._persist_position()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()

    # -- position ----------------------------------------------------------

    def _restore_position(self) -> None:
        cfg = self._settings.value
        self.adjustSize()
        if cfg.float_x >= 0 and cfg.float_y >= 0 and self._on_a_screen(cfg.float_x, cfg.float_y):
            self.move(cfg.float_x, cfg.float_y)
            return
        # Default: bottom-right of the primary screen, clear of the taskbar.
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        if area:
            self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

    def _on_a_screen(self, x: int, y: int) -> bool:
        """Multi-monitor safety: a saved position on a now-absent monitor
        would place the overlay somewhere invisible."""
        for screen in QApplication.screens():
            if screen.availableGeometry().contains(QPoint(x + 8, y + 8)):
                return True
        return False

    def _persist_position(self) -> None:
        point = self.frameGeometry().topLeft()
        snapped = self._snap_to_edge(point)
        if snapped != point:
            self.move(snapped)
        self._settings.update(float_x=snapped.x(), float_y=snapped.y())

    def _snap_to_edge(self, point: QPoint, margin: int = 24) -> QPoint:
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is None:
            return point
        area = screen.availableGeometry()
        x, y = point.x(), point.y()
        if abs(x - area.left()) < margin:
            x = area.left() + 8
        elif abs((x + self.width()) - area.right()) < margin:
            x = area.right() - self.width() - 8
        if abs(y - area.top()) < margin:
            y = area.top() + 8
        elif abs((y + self.height()) - area.bottom()) < margin:
            y = area.bottom() - self.height() - 8
        return QPoint(x, y)
