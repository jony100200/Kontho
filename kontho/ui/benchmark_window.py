"""Benchmark window — a thin shell over kontho.tools.benchmark.

Runs on a worker thread: loading three Whisper models takes tens of seconds and
must not freeze the tray app.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..tools.benchmark import format_report, run_benchmark

log = logging.getLogger("kontho.benchmark_ui")


class _Worker(QObject):
    finished = Signal(str)
    progress = Signal(str)

    def __init__(self, audio_path: str | None, runs: int, show_text: bool):
        super().__init__()
        self._audio = audio_path
        self._runs = runs
        self._show_text = show_text

    def run(self) -> None:
        try:
            results = run_benchmark(self._audio, runs=self._runs,
                                    progress=self.progress.emit)
            self.finished.emit(format_report(results, show_text=self._show_text))
        except Exception as exc:
            log.error("benchmark failed: %s", exc)
            self.finished.emit(f"Benchmark failed:\n{exc}")


class BenchmarkWindow(QWidget):
    def __init__(self, settings_store, registry, controller):
        super().__init__(None)
        self._controller = controller
        self._audio_path = ""
        self._thread: QThread | None = None

        self.setWindowTitle("Kontho — Model Benchmark")
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Measures every installed model on this CPU. Supply a real recording "
            "for meaningful accuracy; without one only speed is measured."
        ))

        row = QHBoxLayout()
        self._audio_label = QLabel("Sample: synthetic tone")
        pick = QPushButton("Choose wav…")
        pick.clicked.connect(self._pick_audio)
        self._runs = QSpinBox()
        self._runs.setRange(1, 10)
        self._runs.setValue(3)
        self._runs.setPrefix("runs: ")
        self._show_text = QCheckBox("Show transcripts")
        row.addWidget(self._audio_label, 1)
        row.addWidget(self._runs)
        row.addWidget(self._show_text)
        row.addWidget(pick)
        layout.addLayout(row)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("Results appear here.")
        self._output.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self._output, 1)

        self._run_button = QPushButton("Run benchmark")
        self._run_button.clicked.connect(self._start)
        layout.addWidget(self._run_button)

    def _pick_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a wav recording", "",
                                              "Audio (*.wav)")
        if path:
            self._audio_path = path
            self._audio_label.setText(f"Sample: {path}")

    def _start(self) -> None:
        if self._thread is not None:
            return
        # Free the model the live pipeline holds, or two copies compete for RAM
        # and the numbers come out wrong.
        self._controller.engine.unload()
        self._run_button.setEnabled(False)
        self._output.setPlainText("Running…")

        thread = QThread(self)
        worker = _Worker(self._audio_path or None, self._runs.value(),
                         self._show_text.isChecked())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(lambda msg: self._output.setPlainText(msg))
        worker.finished.connect(self._done)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _done(self, report: str) -> None:
        self._output.setPlainText(report)
        self._run_button.setEnabled(True)
        if self._thread is not None:
            self._thread.wait(2000)
            self._thread = None
        # Put the live pipeline back the way it was.
        self._controller.load_model(self._controller.settings.value.model_id)
