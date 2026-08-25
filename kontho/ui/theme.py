"""Studio Dark design system for Kontho.

Ultra-lightweight QSS stylesheet and color palette providing a modern,
distraction-free CustomTkinter/Obsidian-inspired dark interface with 0% extra CPU/memory cost.
"""

from __future__ import annotations

# Palette Constants
BG_DARK = "#121316"
BG_CARD = "#1A1C23"
BG_INPUT = "#22252F"
BG_INPUT_HOVER = "#2A2E3B"
BORDER_SUBTLE = "#2E3342"
BORDER_FOCUS = "#00D2FF"
TEXT_MAIN = "#F1F5F9"
TEXT_MUTED = "#94A3B8"
TEXT_DIM = "#64748B"
ACCENT_CYAN = "#00D2FF"
ACCENT_INDIGO = "#6366F1"
ACCENT_GREEN = "#10B981"
ACCENT_RED = "#EF4444"

STUDIO_DARK_QSS = """
/* Global Base */
QWidget {
    background-color: #121316;
    color: #F1F5F9;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Segoe UI Variable", sans-serif;
    font-size: 13px;
    selection-background-color: #00D2FF;
    selection-color: #121316;
}

/* Tab Widget & Segmented Header */
QTabWidget::pane {
    border: 1px solid #2E3342;
    background-color: #1A1C23;
    border-radius: 8px;
    padding: 12px;
    margin-top: 6px;
}

QTabBar::tab {
    background-color: #16181F;
    color: #94A3B8;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid transparent;
    font-weight: 500;
}

QTabBar::tab:hover {
    background-color: #222530;
    color: #F1F5F9;
}

QTabBar::tab:selected {
    background-color: #1A1C23;
    color: #00D2FF;
    border: 1px solid #2E3342;
    border-bottom: 1px solid #1A1C23;
    font-weight: 600;
}

/* Inputs & Form Fields */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #22252F;
    border: 1px solid #2E3342;
    border-radius: 6px;
    padding: 6px 10px;
    color: #F1F5F9;
    min-height: 20px;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #00D2FF;
    background-color: #262936;
}

QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border: 1px solid #3F465A;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #94A3B8;
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #1A1C23;
    border: 1px solid #2E3342;
    selection-background-color: #262A36;
    selection-color: #00D2FF;
    color: #F1F5F9;
    padding: 4px;
    outline: none;
}

/* Buttons */
QPushButton {
    background-color: #262A36;
    color: #F1F5F9;
    border: 1px solid #363C4D;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
    min-height: 18px;
}

QPushButton:hover {
    background-color: #313646;
    border-color: #00D2FF;
    color: #FFFFFF;
}

QPushButton:pressed {
    background-color: #1E212B;
    border-color: #00B4D8;
}

QPushButton:disabled {
    background-color: #1A1C23;
    color: #64748B;
    border-color: #242732;
}

/* Checkboxes */
QCheckBox {
    spacing: 8px;
    color: #F1F5F9;
    font-weight: 500;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #363C4D;
    background-color: #22252F;
}

QCheckBox::indicator:hover {
    border-color: #00D2FF;
}

QCheckBox::indicator:checked {
    background-color: #00D2FF;
    border-color: #00D2FF;
    image: none;
}

/* Lists */
QListWidget {
    background-color: #16181F;
    border: 1px solid #2E3342;
    border-radius: 6px;
    padding: 6px;
    color: #F1F5F9;
    outline: none;
}

QListWidget::item {
    border-radius: 4px;
    padding: 6px 10px;
    margin-bottom: 2px;
}

QListWidget::item:hover {
    background-color: #20232D;
}

QListWidget::item:selected {
    background-color: #262B38;
    color: #00D2FF;
    border: 1px solid #00D2FF;
}

/* Progress Bar */
QProgressBar {
    background-color: #16181F;
    border: 1px solid #2E3342;
    border-radius: 4px;
    text-align: center;
    color: #F1F5F9;
    height: 14px;
}

QProgressBar::chunk {
    background-color: #00D2FF;
    border-radius: 3px;
}

/* Scrollbars */
QScrollBar:vertical {
    background-color: #121316;
    width: 8px;
    margin: 0;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #2E3342;
    border-radius: 4px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background-color: #00D2FF;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Labels & Hints */
QLabel {
    color: #F1F5F9;
}
"""
