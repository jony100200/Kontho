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
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from ..core.controller import State, StatusUpdate

log = logging.getLogger("kontho.overlay")

WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
GWL_EXSTYLE = -20

STATE_COLOURS = {
    State.READY: ("#3B4252", "#D8DEE9", "Ready"),
    State.LISTENING: ("#BF616A", "#FFFFFF", "Listening"),
    State.PROCESSING: ("#D08770", "#FFFFFF", "Working"),
    State.INSERTED: ("#A3BE8C", "#2E3440", "Inserted"),
    State.NO_TARGET: ("#EBCB8B", "#2E3440", "No target"),
    State.ERROR: ("#B48EAD", "#FFFFFF", "Error"),
    State.LOADING: ("#5E81AC", "#FFFFFF", "Loading"),
}


class FloatingOverlay(QWidget):
    """Small always-on-top pill that shows state and a live preview."""

    clicked = Signal()

    def __init__(self, settings_store):
        super().__init__(None)
        self._settings = settings_store
        self._drag_origin: QPoint | None = None
        self._state = State.READY
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

        self._dot = QLabel("●")
        self._dot.setFont(QFont("Segoe UI", 11))
        self._label = QLabel("Kontho")
        self._label.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        self._preview = QLabel("")
        self._preview.setFont(QFont("Segoe UI", 9))
        self._preview.setMaximumWidth(420)
        self._preview.hide()

        layout.addWidget(self._dot)
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
        if state is State.LISTENING and vol > 0.08:
            self._dot.setStyleSheet("color: #FF7B87; font-weight: bold;")
            self._dot.setText("◉")
        else:
            self._dot.setStyleSheet(f"color: {colour};")
            self._dot.setText("●")

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
