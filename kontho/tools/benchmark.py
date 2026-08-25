"""Measure each installed model on this machine, with this CPU, on real audio.

Published Whisper benchmarks are useless for choosing a model here: they are
measured on other hardware, usually on GPUs, and never on Bengali-English code
switching. The only number that matters is the one this box produces.

Reports real-time factor (seconds of compute per second of audio). Below 1.0
means transcription finishes faster than the speech took, which is the bar for
dictation feeling instant.

Usable headless:  python -m kontho.tools.benchmark --audio sample.wav
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ..core.audio import SAMPLE_RATE
from ..core.models import ModelEntry, ModelRegistry
from ..core.settings import DEVICE_CPU, LANG_MIXED, SettingsStore, default_threads
from ..core.stt import create_engine

log = logging.getLogger("kontho.benchmark")


@dataclass
class ModelResult:
    model_id: str
    display_name: str
    load_seconds: float = 0.0
    audio_seconds: float = 0.0
    latencies: list[float] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def mean_latency(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0

    @property
    def real_time_factor(self) -> float:
        if not self.latencies or self.audio_seconds <= 0:
            return 0.0
        return self.mean_latency / self.audio_seconds

    @property
    def verdict(self) -> str:
        if self.error:
            return "failed"
        rtf = self.real_time_factor
        if rtf == 0:
            return "unknown"
        if rtf <= 0.35:
            return "instant"
        if rtf <= 1.0:
            return "comfortable"
        if rtf <= 2.0:
            return "noticeable lag"
        return "too slow for dictation"


def _tone_sample(seconds: float = 4.0) -> np.ndarray:
    """Fallback when no recording is supplied.

    This measures raw throughput only - synthetic audio produces no meaningful
    transcript, so accuracy must be judged from a real recording.
    """
    t = np.linspace(0, seconds, int(SAMPLE_RATE * seconds), endpoint=False, dtype=np.float32)
    speechlike = (
        0.35 * np.sin(2 * np.pi * 140 * t)
        + 0.20 * np.sin(2 * np.pi * 320 * t)
        + 0.10 * np.sin(2 * np.pi * 900 * t)
    )
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 3.5 * t))   # syllable-rate amplitude
    return (speechlike * envelope).astype(np.float32)


def load_wav(path: str | Path) -> np.ndarray:
    """Read a wav to 16 kHz mono float32."""
    import wave

    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())

    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"unsupported sample width: {width} bytes")
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if width == 1:
        data = (data - 128.0) / 128.0
    else:
        data /= float(np.iinfo(dtype).max)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        # Linear resample: adequate for a benchmark, and avoids a scipy dependency.
        target_len = int(len(data) * SAMPLE_RATE / rate)
        data = np.interp(
            np.linspace(0, len(data), target_len, endpoint=False),
            np.arange(len(data)),
            data,
        ).astype(np.float32)
    return np.ascontiguousarray(data, dtype=np.float32)


def benchmark_model(
    entry: ModelEntry,
    audio: np.ndarray,
    *,
    language: str = LANG_MIXED,
    device: str = DEVICE_CPU,
    threads: int = 0,
    runs: int = 3,
    beam_size: int = 0,
) -> ModelResult:
    result = ModelResult(model_id=entry.id, display_name=entry.display_name)
    result.audio_seconds = len(audio) / float(SAMPLE_RATE)
    engine = create_engine("whispercpp")
    try:
        started = time.perf_counter()
        engine.load(entry, device=device, threads=threads or default_threads())
        result.load_seconds = time.perf_counter() - started

        for index in range(max(1, runs)):
            transcript = engine.transcribe(audio, language=language,
                                           sample_rate=SAMPLE_RATE, beam_size=beam_size)
            # Skip the first run: it pays for lazy allocations inside whisper.cpp.
            if index > 0 or runs == 1:
                result.latencies.append(transcript.latency_s)
            result.transcripts.append(transcript.text.strip())
    except Exception as exc:
        result.error = str(exc)
        log.error("benchmark failed for %s: %s", entry.id, exc)
    finally:
        engine.unload()
    return result


def run_benchmark(
    audio_path: str | Path | None = None,
    *,
    model_ids: list[str] | None = None,
    runs: int = 3,
    installed_only: bool = True,
    progress: Callable[[str], None] | None = None,
) -> list[ModelResult]:
    settings = SettingsStore()
    registry = ModelRegistry()
    cfg = settings.value

    audio = load_wav(audio_path) if audio_path else _tone_sample()

    entries = [registry.get(m) for m in model_ids] if model_ids else registry.all()
    entries = [e for e in entries if e is not None]
    if installed_only:
        entries = [e for e in entries if registry.is_installed(e)]
    entries = [e for e in entries if e.supports_language(cfg.language)]

    results: list[ModelResult] = []
    for entry in entries:
        if progress:
            progress(f"Benchmarking {entry.display_name}…")
        results.append(benchmark_model(
            entry, audio,
            language=cfg.language,
            device=cfg.device,
            threads=cfg.threads,
            runs=runs,
            beam_size=cfg.beam_size,
        ))
    return results


def format_report(results: list[ModelResult], *, show_text: bool = False) -> str:
    if not results:
        return "No installed models to benchmark."
    lines = [
        f"{'Model':<24} {'Load':>7} {'Latency':>9} {'RTF':>7}  Verdict",
        "-" * 72,
    ]
    for r in results:
        if r.error:
            lines.append(f"{r.display_name:<24} {'—':>7} {'—':>9} {'—':>7}  {r.error[:28]}")
            continue
        lines.append(
            f"{r.display_name:<24} {r.load_seconds:>6.1f}s {r.mean_latency:>8.2f}s "
            f"{r.real_time_factor:>7.2f}  {r.verdict}"
        )
    lines.append("")
    lines.append(f"Audio sample: {results[0].audio_seconds:.1f}s   "
                 "RTF = compute seconds per audio second (lower is better)")
    if show_text:
        lines.append("")
        for r in results:
            if r.transcripts:
                lines.append(f"{r.display_name}: {r.transcripts[-1][:120]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark Kontho STT models on this machine.")
    parser.add_argument("--audio", help="16 kHz wav of real speech (recommended)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--models", nargs="*", help="model ids; default is every installed model")
    parser.add_argument("--all", action="store_true", help="include models that are not installed")
    parser.add_argument("--text", action="store_true", help="print transcripts too")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    if not args.audio:
        print("No --audio given: measuring throughput on a synthetic tone.\n"
              "Transcript accuracy needs a real recording.\n", file=sys.stderr)

    results = run_benchmark(
        args.audio,
        model_ids=args.models,
        runs=args.runs,
        installed_only=not args.all,
        progress=lambda msg: print(msg, file=sys.stderr),
    )
    print(format_report(results, show_text=args.text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
