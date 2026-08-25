"""The engine room: hotkey -> capture -> VAD -> STT -> shaping -> injection.

The rule this file exists to enforce:

    Window changes must never control the lifetime of microphone capture or STT.

Capture is started by the hotkey and stopped by the hotkey. Nothing about the
foreground window is consulted until a phrase has already been transcribed, and
at that point the window only decides *where the text goes* - never whether
recording continues.

Transcription runs on a worker thread so neither the audio callback nor the UI
ever blocks on whisper.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import numpy as np

from .audio import AudioCapture, SAMPLE_RATE
from .input_bridge import InputBridge
from .models import ModelRegistry
from .settings import (
    MODE_HOLD,
    MODE_TOGGLE,
    SettingsStore,
    TARGET_LOCKED,
)
from .stt import STTEngine, Transcript, create_engine
from .target import TargetManager
from .text_shaping import ShapingConfig, TextShaper
from .vad import EnergyVad, VadConfig, VadEvent

log = logging.getLogger("kontho.controller")


class State(Enum):
    READY = "ready"
    LISTENING = "listening"
    PROCESSING = "processing"
    INSERTED = "inserted"
    NO_TARGET = "no_target"
    ERROR = "error"
    LOADING = "loading"


@dataclass
class StatusUpdate:
    state: State
    detail: str = ""
    preview: str = ""
    target: str = ""
    volume: float = 0.0


class Controller:
    """Owns the pipeline. The UI observes it; it never observes the UI."""

    def __init__(self, settings: SettingsStore, registry: ModelRegistry | None = None):
        self.settings = settings
        self.registry = registry or ModelRegistry()
        self.engine: STTEngine = create_engine("whispercpp")
        self.targets = TargetManager()
        self.bridge = InputBridge(settings.value.inject_method,
                                  pace_ms=settings.value.unicode_pace_ms)

        self._vad = EnergyVad(self._vad_config())
        self._capture: AudioCapture | None = None
        self._jobs: queue.Queue[tuple[np.ndarray, str]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._listening = threading.Event()
        self._model_lock = threading.RLock()

        self._state = State.READY
        self._observers: list[Callable[[StatusUpdate], None]] = []
        self._last_error = ""
        self._last_vol_time = 0.0
        self.last_transcript: Transcript | None = None

    # -- observation -------------------------------------------------------

    def subscribe(self, callback: Callable[[StatusUpdate], None]) -> None:
        self._observers.append(callback)

    def _emit(self, state: State, detail: str = "", preview: str = "", volume: float = 0.0) -> None:
        self._state = state
        update = StatusUpdate(state=state, detail=detail, preview=preview,
                              target=str(self.targets.foreground()), volume=volume)
        for callback in list(self._observers):
            try:
                callback(update)
            except Exception as exc:
                log.error("observer raised: %s", exc)

    @property
    def state(self) -> State:
        return self._state

    @property
    def listening(self) -> bool:
        return self._listening.is_set()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the worker and load the configured model."""
        self._stop.clear()
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._worker_loop, daemon=True,
                                            name="kontho-stt")
            self._worker.start()
        self.load_model(self.settings.value.model_id)

    def shutdown(self) -> None:
        self._stop.set()
        self.stop_listening(finalize=False)
        if self._capture is not None:
            self._capture.stop()
            self._capture = None
        self._jobs.put((np.zeros(0, dtype=np.float32), ""))  # wake the worker
        if self._worker is not None:
            self._worker.join(timeout=3.0)
        with self._model_lock:
            self.engine.unload()

    # -- model management --------------------------------------------------

    def load_model(self, model_id: str) -> bool:
        """Switch models without restarting anything.

        New jobs are refused, the old model is released, the new one loads.
        """
        cfg = self.settings.value
        entry = self.registry.resolve(model_id, cfg.language)
        if entry.notes and entry.id != model_id:
            log.warning(entry.notes)

        with self._model_lock:
            self._emit(State.LOADING, f"Loading {entry.display_name}…")
            try:
                if not self.registry.is_installed(entry):
                    self._emit(State.LOADING, f"Downloading {entry.display_name} ({entry.model_size})…")
                    self.registry.download(entry.id)
                self.engine.unload()
                self.engine.load(entry, device=cfg.device, threads=cfg.threads)
                self.settings.update(model_id=entry.id)
                self._emit(State.READY, f"{entry.display_name} ready")
                return True
            except Exception as exc:
                self._last_error = str(exc)
                log.error("model load failed: %s", exc)
                self._emit(State.ERROR, f"Model load failed: {exc}")
                return False

    # -- listening ---------------------------------------------------------

    def toggle(self) -> None:
        if self._listening.is_set():
            self.stop_listening()
        else:
            self.start_listening()

    def on_hotkey_press(self) -> None:
        mode = self.settings.value.listen_mode
        if mode == MODE_TOGGLE:
            self.toggle()
        else:
            self.start_listening()

    def on_hotkey_release(self) -> None:
        if self.settings.value.listen_mode == MODE_HOLD:
            self.stop_listening()

    def start_listening(self) -> None:
        if self._listening.is_set():
            return
        cfg = self.settings.value

        # Lock the target now if the user asked for locked mode. In dynamic
        # mode we deliberately do not look at the window at all yet.
        if cfg.target_mode == TARGET_LOCKED:
            self.targets.lock_current()

        self._vad = EnergyVad(self._vad_config())
        if self._capture is None:
            self._capture = AudioCapture(cfg.input_device, on_block=self._on_block)
        if not self._capture.running and not self._capture.start():
            self._emit(State.ERROR, f"Microphone unavailable: {self._capture.error}")
            return

        self._listening.set()
        log.info("listening started (mode=%s target=%s)", cfg.listen_mode, cfg.target_mode)
        self._emit(State.LISTENING, "Listening")

    def stop_listening(self, *, finalize: bool = True) -> None:
        if not self._listening.is_set():
            return
        self._listening.clear()
        log.info("listening stopped")

        if finalize:
            tail = self._vad.flush()
            if tail.size:
                self._queue_job(tail)
                self._emit(State.PROCESSING, "Finalising…")
            else:
                self._emit(State.READY, "Ready")
        # The capture stream stays open: reopening a WASAPI device per phrase
        # is slow and loses the first syllable.
        if self.settings.value.target_mode == TARGET_LOCKED:
            self.targets.unlock()

    # -- audio thread ------------------------------------------------------

    def _on_block(self, block: np.ndarray) -> None:
        """Audio callback. Must stay cheap."""
        if not self._listening.is_set():
            return
        event = self._vad.push(block)
        now = time.perf_counter()
        if now - self._last_vol_time >= 0.05:
            self._last_vol_time = now
            rms = float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0
            vol = min(1.0, max(0.0, (rms - 0.003) * 25.0))
            self._emit(State.LISTENING, "Listening", volume=vol)

        if event is VadEvent.SPEECH_END:
            phrase = self._vad.take_phrase()
            if phrase.size:
                self._queue_job(phrase)

    def _queue_job(self, audio: np.ndarray) -> None:
        # Capture the target mode now; the user could change it mid-phrase.
        self._jobs.put((audio, self.settings.value.target_mode))

    # -- worker thread -----------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                audio, target_mode = self._jobs.get(timeout=0.3)
            except queue.Empty:
                continue
            if audio.size == 0:
                continue
            try:
                self._process(audio, target_mode)
            except Exception as exc:
                log.error("transcription job failed: %s", exc)
                self._emit(State.ERROR, str(exc))

    def _process(self, audio: np.ndarray, target_mode: str) -> None:
        cfg = self.settings.value
        duration = len(audio) / float(SAMPLE_RATE)
        if duration < (cfg.min_speech_ms / 1000.0):
            return

        with self._model_lock:
            if not self.engine.loaded:
                self._emit(State.ERROR, "No model loaded")
                return
            self._emit(State.PROCESSING, "Transcribing…")
            transcript = self.engine.transcribe(
                audio,
                language=cfg.language,
                sample_rate=SAMPLE_RATE,
                beam_size=cfg.beam_size,
            )

        self.last_transcript = transcript
        if cfg.log_transcripts:
            log.info("transcript: %s", transcript.text)
        log.info("stt done: %.2fs audio in %.2fs (rtf %.2f)",
                 transcript.duration_s, transcript.latency_s, transcript.real_time_factor)

        if not transcript.text.strip():
            self._emit(State.LISTENING if self._listening.is_set() else State.READY, "")
            return

        self._deliver(transcript, target_mode)

    def _deliver(self, transcript: Transcript, target_mode: str) -> None:
        cfg = self.settings.value
        target = self.targets.resolve(target_mode)
        if not target.valid:
            log.warning("no editable target for finalised text")
            self._emit(State.NO_TARGET, "No editable target — text not inserted")
            return

        # A terminal gets literal text regardless of the configured profile,
        # because "Git status." is simply wrong in a shell.
        profile = "terminal" if target.is_terminal else cfg.profile
        shaper = TextShaper(ShapingConfig(
            profile=profile,
            vocabulary=cfg.vocabulary,
            replacements=cfg.replacements,
            voice_commands=cfg.voice_commands,
            trailing_space=cfg.trailing_space,
        ))
        text = shaper.shape(transcript.text)
        if not text:
            return

        if target_mode == TARGET_LOCKED:
            self.targets.focus(target)
            time.sleep(0.03)

        self.bridge.pace_ms = cfg.unicode_pace_ms
        result = self.bridge.send(text, method=cfg.inject_method)
        log.info("insert %s via %s -> %s", "ok" if result.ok else "FAILED",
                 result.method, target)
        if result.ok:
            self._emit(
                State.LISTENING if self._listening.is_set() else State.INSERTED,
                f"Inserted into {target.process or 'window'}",
            )
        else:
            self._emit(State.ERROR, f"Insertion failed: {result.error}")

    # -- helpers -----------------------------------------------------------

    def _vad_config(self) -> VadConfig:
        cfg = self.settings.value
        return VadConfig(
            threshold=cfg.vad_threshold,
            min_speech_ms=cfg.min_speech_ms,
            silence_ms=cfg.silence_ms,
            speech_pad_ms=cfg.speech_pad_ms,
            sample_rate=cfg.sample_rate,
        )

    def apply_audio_settings(self) -> None:
        """Called when the microphone selection changes."""
        if self._capture is not None:
            self._capture.restart(self.settings.value.input_device)
