"""Compact settings window.

Deliberately a small tabbed dialog, not a dashboard. Every control writes
straight through to the settings store, and anything that needs the pipeline to
react (microphone, model) calls the controller rather than mutating it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import audio as audio_mod
from ..core.settings import (
    DEVICE_AUTO,
    DEVICE_CPU,
    DEVICE_GPU,
    LANGUAGES,
    MODE_HOLD,
    MODE_TOGGLE,
    PROFILES,
    TARGET_DYNAMIC,
    TARGET_LOCKED,
)

log = logging.getLogger("kontho.settings_ui")


class SettingsWindow(QWidget):
    hotkey_changed = Signal(str)
    model_changed = Signal(str)
    audio_changed = Signal()
    benchmark_requested = Signal()

    def __init__(self, settings_store, registry, controller):
        super().__init__(None)
        self._settings = settings_store
        self._registry = registry
        self._controller = controller

        self.setWindowTitle("Kontho — Settings")
        self.resize(520, 480)

        tabs = QTabWidget(self)
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._audio_tab(), "Audio")
        tabs.addTab(self._recognition_tab(), "Recognition")
        tabs.addTab(self._typing_tab(), "Typing")
        tabs.addTab(self._vocabulary_tab(), "Vocabulary")
        tabs.addTab(self._models_tab(), "Models")
        tabs.addTab(self._advanced_tab(), "Advanced")

        root = QVBoxLayout(self)
        root.addWidget(tabs)

    # -- tabs --------------------------------------------------------------

    def _general_tab(self) -> QWidget:
        cfg = self._settings.value
        page = QWidget()
        form = QFormLayout(page)

        self._startup = QCheckBox("Start Kontho with Windows")
        self._startup.setChecked(cfg.start_with_windows)
        self._startup.toggled.connect(self._on_startup_toggled)
        form.addRow(self._startup)

        self._show_float = QCheckBox("Show floating control")
        self._show_float.setChecked(cfg.show_floating)
        self._show_float.toggled.connect(lambda v: self._settings.update(show_floating=v))
        form.addRow(self._show_float)

        self._hotkey = QLineEdit(cfg.hotkey)
        self._hotkey.setPlaceholderText("ctrl+shift+space")
        apply_hotkey = QPushButton("Apply")
        apply_hotkey.clicked.connect(self._on_hotkey_apply)
        row = QHBoxLayout()
        row.addWidget(self._hotkey)
        row.addWidget(apply_hotkey)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow("Push-to-talk hotkey", holder)

        self._mode = QComboBox()
        self._mode.addItem("Hold to talk", MODE_HOLD)
        self._mode.addItem("Toggle listening", MODE_TOGGLE)
        self._mode.setCurrentIndex(0 if cfg.listen_mode == MODE_HOLD else 1)
        self._mode.currentIndexChanged.connect(
            lambda: self._settings.update(listen_mode=self._mode.currentData())
        )
        form.addRow("Listening mode", self._mode)
        return page

    def _audio_tab(self) -> QWidget:
        cfg = self._settings.value
        page = QWidget()
        form = QFormLayout(page)

        self._mic = QComboBox()
        self._mic.addItem("System default", "")
        for dev in audio_mod.list_input_devices():
            label = f"{dev.name}{'  (default)' if dev.default else ''}"
            self._mic.addItem(label, dev.name)
        index = self._mic.findData(cfg.input_device)
        self._mic.setCurrentIndex(index if index >= 0 else 0)
        self._mic.currentIndexChanged.connect(self._on_mic_changed)
        form.addRow("Microphone", self._mic)

        note = QLabel("Capture runs at 16 kHz mono and stays open while you dictate.")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _recognition_tab(self) -> QWidget:
        cfg = self._settings.value
        page = QWidget()
        form = QFormLayout(page)

        self._model = QComboBox()
        self._reload_model_combo()
        self._model.currentIndexChanged.connect(self._on_model_changed)
        form.addRow("Recognition model", self._model)

        self._language = QComboBox()
        for lang in LANGUAGES:
            self._language.addItem({"bn+en": "Bengali + English",
                                    "bn": "Bengali",
                                    "en": "English",
                                    "auto": "Auto"}[lang], lang)
        self._language.setCurrentIndex(max(0, self._language.findData(cfg.language)))
        self._language.currentIndexChanged.connect(self._on_language_changed)
        form.addRow("Language", self._language)

        self._device = QComboBox()
        self._device.addItem("CPU (default)", DEVICE_CPU)
        self._device.addItem("GPU (optional)", DEVICE_GPU)
        self._device.addItem("Auto", DEVICE_AUTO)
        self._device.setCurrentIndex(max(0, self._device.findData(cfg.device)))
        self._device.currentIndexChanged.connect(
            lambda: self._settings.update(device=self._device.currentData())
        )
        form.addRow("Compute device", self._device)

        self._threads = QSpinBox()
        self._threads.setRange(1, 32)
        self._threads.setValue(cfg.threads)
        self._threads.valueChanged.connect(lambda v: self._settings.update(threads=v))
        form.addRow("CPU threads", self._threads)

        hint = QLabel("CPU is the default so Kontho does not take VRAM from other AI tools.")
        hint.setWordWrap(True)
        form.addRow(hint)
        return page

    def _typing_tab(self) -> QWidget:
        cfg = self._settings.value
        page = QWidget()
        form = QFormLayout(page)

        self._target = QComboBox()
        self._target.addItem("Dynamic — whatever has focus", TARGET_DYNAMIC)
        self._target.addItem("Locked — the window I started in", TARGET_LOCKED)
        self._target.setCurrentIndex(max(0, self._target.findData(cfg.target_mode)))
        self._target.currentIndexChanged.connect(
            lambda: self._settings.update(target_mode=self._target.currentData())
        )
        form.addRow("Target mode", self._target)

        self._profile = QComboBox()
        for prof in PROFILES:
            self._profile.addItem(prof.title(), prof)
        self._profile.setCurrentIndex(max(0, self._profile.findData(cfg.profile)))
        self._profile.currentIndexChanged.connect(
            lambda: self._settings.update(profile=self._profile.currentData())
        )
        form.addRow("Application profile", self._profile)

        self._inject = QComboBox()
        for label, value in (("Auto", "auto"), ("Unicode keystrokes", "unicode"),
                             ("Clipboard paste", "clipboard")):
            self._inject.addItem(label, value)
        self._inject.setCurrentIndex(max(0, self._inject.findData(cfg.inject_method)))
        self._inject.currentIndexChanged.connect(self._on_inject_changed)
        form.addRow("Insertion method", self._inject)

        self._pace = QDoubleSpinBox()
        self._pace.setRange(0.0, 60.0)
        self._pace.setSingleStep(1.0)
        self._pace.setDecimals(1)
        self._pace.setSuffix(" ms")
        self._pace.setValue(cfg.unicode_pace_ms)
        self._pace.setToolTip(
            "Gap between typed characters. Below about 12 ms the target "
            "application cannot keep up and the text arrives corrupted. "
            "Raise it if a slow application drops characters."
        )
        self._pace.valueChanged.connect(self._on_pace_changed)
        form.addRow("Typing speed", self._pace)

        self._commands = QCheckBox('Spoken punctuation ("new line", "comma")')
        self._commands.setChecked(cfg.voice_commands)
        self._commands.toggled.connect(lambda v: self._settings.update(voice_commands=v))
        form.addRow(self._commands)

        note = QLabel("Terminals always receive literal text, whatever the profile.")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _vocabulary_tab(self) -> QWidget:
        cfg = self._settings.value
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel("Terms to preserve (one per line):"))
        self._vocab = QListWidget()
        self._vocab.addItems(cfg.vocabulary)
        layout.addWidget(self._vocab)

        entry_row = QHBoxLayout()
        self._vocab_entry = QLineEdit()
        self._vocab_entry.setPlaceholderText("Godot")
        add = QPushButton("Add")
        remove = QPushButton("Remove")
        add.clicked.connect(self._add_vocab)
        remove.clicked.connect(self._remove_vocab)
        entry_row.addWidget(self._vocab_entry)
        entry_row.addWidget(add)
        entry_row.addWidget(remove)
        layout.addLayout(entry_row)

        layout.addWidget(QLabel('Replacements — spoken → written (e.g. "go dot" → Godot):'))
        self._rules = QListWidget()
        for spoken, written in (cfg.replacements or {}).items():
            self._rules.addItem(f"{spoken} → {written}")
        layout.addWidget(self._rules)

        rule_row = QHBoxLayout()
        self._rule_from = QLineEdit()
        self._rule_from.setPlaceholderText("go dot")
        self._rule_to = QLineEdit()
        self._rule_to.setPlaceholderText("Godot")
        add_rule = QPushButton("Add rule")
        add_rule.clicked.connect(self._add_rule)
        rule_row.addWidget(self._rule_from)
        rule_row.addWidget(self._rule_to)
        rule_row.addWidget(add_rule)
        layout.addLayout(rule_row)
        return page

    def _models_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._model_list = QListWidget()
        layout.addWidget(self._model_list)
        self._refresh_model_list()

        self._progress = QProgressBar()
        self._progress.hide()
        layout.addWidget(self._progress)

        row = QHBoxLayout()
        download = QPushButton("Download selected")
        add_local = QPushButton("Add local model…")
        remove = QPushButton("Remove")
        open_folder = QPushButton("Open folder")
        bench = QPushButton("Benchmark…")
        download.clicked.connect(self._download_selected)
        add_local.clicked.connect(self._add_local_model)
        remove.clicked.connect(self._remove_selected)
        open_folder.clicked.connect(self._open_models_folder)
        bench.clicked.connect(self.benchmark_requested)
        for button in (download, add_local, remove, open_folder, bench):
            row.addWidget(button)
        layout.addLayout(row)
        return page

    def _advanced_tab(self) -> QWidget:
        cfg = self._settings.value
        page = QWidget()
        form = QFormLayout(page)

        self._vad_threshold = QDoubleSpinBox()
        self._vad_threshold.setRange(0.001, 0.2)
        self._vad_threshold.setSingleStep(0.002)
        self._vad_threshold.setDecimals(3)
        self._vad_threshold.setValue(cfg.vad_threshold)
        self._vad_threshold.valueChanged.connect(lambda v: self._settings.update(vad_threshold=v))
        form.addRow("VAD threshold", self._vad_threshold)

        self._min_speech = QSpinBox()
        self._min_speech.setRange(50, 2000)
        self._min_speech.setSingleStep(50)
        self._min_speech.setSuffix(" ms")
        self._min_speech.setValue(cfg.min_speech_ms)
        self._min_speech.valueChanged.connect(lambda v: self._settings.update(min_speech_ms=v))
        form.addRow("Minimum speech", self._min_speech)

        self._silence = QSpinBox()
        self._silence.setRange(200, 3000)
        self._silence.setSingleStep(50)
        self._silence.setSuffix(" ms")
        self._silence.setValue(cfg.silence_ms)
        self._silence.valueChanged.connect(lambda v: self._settings.update(silence_ms=v))
        form.addRow("Phrase pause", self._silence)

        self._pad = QSpinBox()
        self._pad.setRange(0, 1000)
        self._pad.setSingleStep(50)
        self._pad.setSuffix(" ms")
        self._pad.setValue(cfg.speech_pad_ms)
        self._pad.valueChanged.connect(lambda v: self._settings.update(speech_pad_ms=v))
        form.addRow("Speech padding", self._pad)

        self._beam = QSpinBox()
        self._beam.setRange(0, 8)
        self._beam.setValue(cfg.beam_size)
        self._beam.valueChanged.connect(lambda v: self._settings.update(beam_size=v))
        form.addRow("Beam size (0 = greedy)", self._beam)

        self._log_text = QCheckBox("Log transcribed text (off by default for privacy)")
        self._log_text.setChecked(cfg.log_transcripts)
        self._log_text.toggled.connect(lambda v: self._settings.update(log_transcripts=v))
        form.addRow(self._log_text)
        return page

    # -- handlers ----------------------------------------------------------

    def _on_startup_toggled(self, enabled: bool) -> None:
        from ..core.startup import set_run_at_startup

        ok, message = set_run_at_startup(enabled)
        self._settings.update(start_with_windows=enabled and ok)
        if not ok:
            QMessageBox.warning(self, "Kontho", f"Could not change startup setting:\n{message}")
            self._startup.setChecked(False)

    def _on_hotkey_apply(self) -> None:
        combo = self._hotkey.text().strip().lower()
        if not combo:
            return
        self._settings.update(hotkey=combo)
        self.hotkey_changed.emit(combo)

    def _on_mic_changed(self) -> None:
        self._settings.update(input_device=self._mic.currentData() or "")
        self.audio_changed.emit()

    def _on_inject_changed(self) -> None:
        method = self._inject.currentData()
        self._settings.update(inject_method=method)
        self._controller.bridge.method = method

    def _on_pace_changed(self, value: float) -> None:
        if 0 < value < 12:
            log.warning("typing pace %.1f ms is below the measured corruption "
                        "threshold of ~12 ms", value)
        self._settings.update(unicode_pace_ms=value)
        self._controller.bridge.pace_ms = value

    def _on_language_changed(self) -> None:
        language = self._language.currentData()
        self._settings.update(language=language)
        # An English-only model cannot serve Bengali; refresh what is offered.
        self._reload_model_combo()

    def _on_model_changed(self) -> None:
        model_id = self._model.currentData()
        if model_id and model_id != self._settings.value.model_id:
            self.model_changed.emit(model_id)

    def _reload_model_combo(self) -> None:
        cfg = self._settings.value
        self._model.blockSignals(True)
        self._model.clear()
        for entry in self._registry.for_language(cfg.language):
            suffix = "" if entry.installed else "  (not installed)"
            self._model.addItem(f"{entry.display_name}{suffix}", entry.id)
        index = self._model.findData(cfg.model_id)
        self._model.setCurrentIndex(index if index >= 0 else 0)
        self._model.blockSignals(False)

    def _refresh_model_list(self) -> None:
        self._model_list.clear()
        for entry in self._registry.all():
            state = "installed" if entry.installed else "not installed"
            flag = " · experimental" if entry.experimental else ""
            self._model_list.addItem(
                f"{entry.display_name} — {entry.model_size} — {state}{flag}"
            )

    def _selected_model_id(self) -> str | None:
        row = self._model_list.currentRow()
        entries = self._registry.all()
        if 0 <= row < len(entries):
            return entries[row].id
        return None

    def _download_selected(self) -> None:
        model_id = self._selected_model_id()
        if not model_id:
            return
        self._progress.show()
        self._progress.setValue(0)

        def progress(done: int, total: int) -> None:
            if total:
                self._progress.setValue(int(done * 100 / total))

        try:
            self._registry.download(model_id, progress)
            QMessageBox.information(self, "Kontho", "Model downloaded.")
        except Exception as exc:
            QMessageBox.warning(self, "Kontho", f"Download failed:\n{exc}")
        finally:
            self._progress.hide()
            self._refresh_model_list()
            self._reload_model_combo()

    def _add_local_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select a GGML/GGUF model", "",
                                              "Models (*.bin *.gguf);;All files (*)")
        if not path:
            return
        try:
            self._registry.add_local(path)
            self._refresh_model_list()
            self._reload_model_combo()
        except Exception as exc:
            QMessageBox.warning(self, "Kontho", f"Could not add model:\n{exc}")

    def _remove_selected(self) -> None:
        model_id = self._selected_model_id()
        if not model_id:
            return
        confirm = QMessageBox.question(
            self, "Kontho", f"Remove {model_id}?\nThe model file will be deleted."
        )
        if confirm != QMessageBox.Yes:
            return
        self._registry.remove(model_id, delete_file=True)
        self._refresh_model_list()
        self._reload_model_combo()

    def _open_models_folder(self) -> None:
        import os

        os.startfile(str(self._registry.open_folder()))

    def _add_vocab(self) -> None:
        term = self._vocab_entry.text().strip()
        if not term:
            return
        terms = list(self._settings.value.vocabulary)
        if term not in terms:
            terms.append(term)
            self._settings.update(vocabulary=terms)
            self._vocab.addItem(term)
        self._vocab_entry.clear()

    def _remove_vocab(self) -> None:
        row = self._vocab.currentRow()
        if row < 0:
            return
        terms = list(self._settings.value.vocabulary)
        if row < len(terms):
            terms.pop(row)
            self._settings.update(vocabulary=terms)
        self._vocab.takeItem(row)

    def _add_rule(self) -> None:
        spoken = self._rule_from.text().strip().lower()
        written = self._rule_to.text().strip()
        if not spoken or not written:
            return
        rules = dict(self._settings.value.replacements)
        rules[spoken] = written
        self._settings.update(replacements=rules)
        self._rules.addItem(f"{spoken} → {written}")
        self._rule_from.clear()
        self._rule_to.clear()
