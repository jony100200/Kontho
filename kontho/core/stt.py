"""STT engine interface and the whisper.cpp implementation.

Nothing above this module knows which engine is running. Adding another
backend means writing another `STTEngine`, not editing the controller.

Model lifetime is explicit: `unload()` really releases the previous model
before a new one loads, so switching does not leave two large models resident.
"""

from __future__ import annotations

import logging
import re as _re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .models import ModelEntry
from .settings import (
    DEVICE_AUTO,
    DEVICE_CPU,
    DEVICE_GPU,
    LANG_AUTO,
    LANG_BN,
    LANG_EN,
    LANG_MIXED,
)

log = logging.getLogger("kontho.stt")


@dataclass
class Transcript:
    text: str
    language: str = ""
    duration_s: float = 0.0
    latency_s: float = 0.0
    is_final: bool = True

    @property
    def real_time_factor(self) -> float:
        """<1.0 means faster than real time."""
        if self.duration_s <= 0:
            return 0.0
        return self.latency_s / self.duration_s


@dataclass
class EngineCapabilities:
    streaming: bool = False
    languages: tuple[str, ...] = ("multilingual",)
    gpu: bool = False
    translate: bool = False
    name: str = "engine"


class STTEngine(ABC):
    """One transcription backend."""

    @abstractmethod
    def load(self, entry: ModelEntry, *, device: str = DEVICE_CPU, threads: int = 4) -> None: ...

    @abstractmethod
    def unload(self) -> None: ...

    @abstractmethod
    def transcribe(self, audio: np.ndarray, *, language: str = LANG_MIXED,
                   sample_rate: int = 16000, beam_size: int = 0) -> Transcript: ...

    @abstractmethod
    def capabilities(self) -> EngineCapabilities: ...

    @abstractmethod
    def model_metadata(self) -> dict[str, Any]: ...

    @property
    @abstractmethod
    def loaded(self) -> bool: ...

    # Streaming is optional; the default is "collect then transcribe", which is
    # what whisper.cpp genuinely does. Engines that stream can override.
    def start_stream(self, **kwargs: Any) -> None:
        self._stream_chunks: list[np.ndarray] = []

    def accept_audio(self, chunk: np.ndarray) -> None:
        if not hasattr(self, "_stream_chunks"):
            self.start_stream()
        self._stream_chunks.append(chunk)

    def finalize(self, **kwargs: Any) -> Transcript:
        chunks = getattr(self, "_stream_chunks", [])
        self._stream_chunks = []
        if not chunks:
            return Transcript(text="", is_final=True)
        return self.transcribe(np.concatenate(chunks), **kwargs)


# Whisper's own language codes. "bn+en" has no single code: Whisper is told
# Bengali and left to keep the English technical words it hears, which is what
# actually happens in mixed speech. Auto lets it decide per utterance.
_WHISPER_LANG = {
    LANG_MIXED: "bn",
    LANG_BN: "bn",
    LANG_EN: "en",
    LANG_AUTO: "auto",
}

# Whisper annotates non-speech instead of returning nothing: silence becomes
# "[BLANK_AUDIO]", a fan becomes "(wind blowing)", music becomes "[Music]".
# These are descriptions of the audio, not dictation, and typing them into the
# user's document would be a visible bug. Measured on this box: a synthetic
# tone transcribes as "[Music]".
_ANNOTATION = _re.compile(r"^\s*[\[\(\*][^\]\)\*]*[\]\)\*]\s*$")
_INLINE_ANNOTATION = _re.compile(r"[\[\(][^\]\)]{0,40}[\]\)]")


def strip_non_speech(text: str) -> str:
    """Remove Whisper's non-speech annotations.

    A segment that is *only* an annotation disappears. Annotations mixed into
    real speech are cut out and the remaining words kept.
    """
    if not text:
        return ""
    if _ANNOTATION.match(text):
        return ""
    cleaned = _INLINE_ANNOTATION.sub(" ", text)
    return _re.sub(r"\s{2,}", " ", cleaned).strip()


class WhisperCppEngine(STTEngine):
    """whisper.cpp via pywhispercpp. CPU by default, never touches the GPU."""

    def __init__(self) -> None:
        self._model = None
        self._entry: ModelEntry | None = None
        self._threads = 4
        self._device = DEVICE_CPU
        self._lock = threading.RLock()
        self._load_seconds = 0.0

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, entry: ModelEntry, *, device: str = DEVICE_CPU, threads: int = 4) -> None:
        from pywhispercpp.model import Model

        with self._lock:
            self.unload()
            started = time.perf_counter()
            # A custom entry carries an explicit file; a preset is fetched or
            # found by name in whisper.cpp's own store.
            # Always an explicit file path when we have one. Passing a bare id
            # lets pywhispercpp resolve it against its own store and download a
            # second copy of the model.
            target = entry.path if entry.path else entry.id

            # `device` has to reach whisper.cpp, not just sit in settings.
            # Without use_gpu=False the backend probes for CUDA and, on a build
            # that has it, takes VRAM the image and video work needs.
            use_gpu = device in (DEVICE_GPU, DEVICE_AUTO)

            params: dict[str, Any] = {
                "n_threads": max(1, int(threads)),
                # whisper.cpp otherwise writes a progress bar to the console.
                "print_progress": False,
                "print_realtime": False,
                "print_timestamps": False,
                "print_special": False,
            }
            log.info("loading model=%s device=%s use_gpu=%s threads=%s path=%s",
                     entry.id, device, use_gpu, threads, target)
            # Ensure standard streams are valid files before pywhispercpp redirect_stderr flushes
            import os
            import sys
            if sys.stdout is None:
                sys.stdout = open(os.devnull, "w", encoding="utf-8")
            if sys.stderr is None:
                sys.stderr = open(os.devnull, "w", encoding="utf-8")

            try:
                self._model = Model(
                    target,
                    context_params={"use_gpu": use_gpu},
                    redirect_whispercpp_logs_to=None,
                    **params,
                )
            except (TypeError, AttributeError, Exception) as exc:
                log.warning("binding initialisation fallback (%s); loading with basic params", exc)
                self._model = Model(target, n_threads=max(1, int(threads)))
            self._entry = entry
            self._threads = threads
            self._device = device
            self._load_seconds = time.perf_counter() - started
            log.info("model %s ready in %.2fs", entry.id, self._load_seconds)

    def unload(self) -> None:
        with self._lock:
            if self._model is None:
                return
            log.info("unloading model=%s", self._entry.id if self._entry else "?")
            # Drop the binding and let the allocator reclaim it before the next
            # load, so two models are never resident at once.
            self._model = None
            self._entry = None
            import gc

            gc.collect()

    def transcribe(self, audio: np.ndarray, *, language: str = LANG_MIXED,
                   sample_rate: int = 16000, beam_size: int = 0) -> Transcript:
        with self._lock:
            if self._model is None:
                raise RuntimeError("no model loaded")
            samples = _as_float32_mono(audio)
            duration = len(samples) / float(sample_rate or 16000)
            whisper_lang = _WHISPER_LANG.get(language, "auto")

            kwargs: dict[str, Any] = {
                "language": whisper_lang,
                # Transcription, never translation - the spec is explicit.
                "translate": False,
                "n_threads": self._threads,
            }
            if beam_size and beam_size > 1:
                kwargs["beam_search"] = {"beam_size": int(beam_size)}

            started = time.perf_counter()
            try:
                segments = self._model.transcribe(samples, **kwargs)
            except TypeError:
                # Older binding signatures accept fewer keywords.
                segments = self._model.transcribe(samples, language=whisper_lang)
            latency = time.perf_counter() - started

            parts = [strip_non_speech((getattr(s, "text", "") or "").strip())
                     for s in segments]
            text = " ".join(p for p in parts if p).strip()
            return Transcript(
                text=text,
                language=whisper_lang,
                duration_s=duration,
                latency_s=latency,
                is_final=True,
            )

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            streaming=False,
            languages=("multilingual", "bn", "en"),
            gpu=False,
            translate=False,
            name="whisper.cpp",
        )

    def model_metadata(self) -> dict[str, Any]:
        if self._entry is None:
            return {"loaded": False}
        return {
            "loaded": True,
            "id": self._entry.id,
            "display_name": self._entry.display_name,
            "quantization": self._entry.quantization,
            "engine": "whisper.cpp",
            "device": self._device,
            "threads": self._threads,
            "load_seconds": round(self._load_seconds, 3),
        }


def _as_float32_mono(audio: np.ndarray) -> np.ndarray:
    """whisper.cpp wants mono float32 in [-1, 1]."""
    data = np.asarray(audio)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype != np.float32:
        data = data.astype(np.float32)
    return np.ascontiguousarray(data)


def create_engine(name: str = "whispercpp") -> STTEngine:
    if name in ("whispercpp", "whisper.cpp", "whisper"):
        return WhisperCppEngine()
    raise ValueError(f"unknown STT engine: {name}")
