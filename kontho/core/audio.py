"""Microphone capture: 16 kHz mono, continuous, never on the UI thread.

Capture deliberately does not know about hotkeys, windows or focus. It fills a
ring buffer for as long as the stream is open; whether those samples are *used*
is somebody else's decision. That separation is what stops a window change from
killing the microphone.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

log = logging.getLogger("kontho.audio")

SAMPLE_RATE = 16000
BLOCK_MS = 32
BLOCK_SAMPLES = SAMPLE_RATE * BLOCK_MS // 1000


@dataclass
class InputDevice:
    index: int
    name: str
    channels: int
    default: bool = False


def list_input_devices() -> list[InputDevice]:
    import sounddevice as sd

    try:
        default_index = sd.default.device[0]
    except Exception:
        default_index = None
    rows: list[InputDevice] = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            rows.append(
                InputDevice(
                    index=idx,
                    name=str(dev.get("name", f"device {idx}")),
                    channels=int(dev["max_input_channels"]),
                    default=(idx == default_index),
                )
            )
    return rows


def resolve_device(name_substring: str = "") -> tuple[int | None, str]:
    """Match a device by name fragment; fall back to the system default."""
    devices = list_input_devices()
    if name_substring:
        needle = name_substring.lower()
        for dev in devices:
            if needle in dev.name.lower():
                return dev.index, dev.name
        log.warning("microphone %r not found; using default", name_substring)
    for dev in devices:
        if dev.default:
            return dev.index, dev.name
    if devices:
        return devices[0].index, devices[0].name
    return None, "no input device"


class AudioCapture:
    """Continuous capture into a bounded ring buffer.

    `on_block` runs on the audio callback thread and must stay cheap - it only
    feeds the VAD. Anything slow belongs on the worker thread.
    """

    def __init__(self, device_name: str = "", ring_seconds: float = 30.0,
                 on_block: Callable[[np.ndarray], None] | None = None):
        self._device_name = device_name
        self._on_block = on_block
        self._stream = None
        self._lock = threading.RLock()
        self._ring: deque[np.ndarray] = deque(maxlen=int(ring_seconds * 1000 / BLOCK_MS))
        self.device_index: int | None = None
        self.device_label = ""
        self._error: str = ""

    @property
    def running(self) -> bool:
        return self._stream is not None

    @property
    def error(self) -> str:
        return self._error

    def start(self) -> bool:
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return True
            self.device_index, self.device_label = resolve_device(self._device_name)
            try:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK_SAMPLES,
                    channels=1,
                    dtype="float32",
                    device=self.device_index,
                    callback=self._callback,
                )
                self._stream.start()
                self._error = ""
                log.info("microphone open: %s", self.device_label)
                return True
            except Exception as exc:
                self._stream = None
                self._error = str(exc)
                log.error("microphone open failed: %s", exc)
                return False

    def stop(self) -> None:
        with self._lock:
            if self._stream is None:
                return
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                log.warning("microphone close: %s", exc)
            finally:
                self._stream = None
                log.info("microphone closed")

    def restart(self, device_name: str | None = None) -> bool:
        """Used when the user picks another mic, or a device disappears."""
        if device_name is not None:
            self._device_name = device_name
        self.stop()
        return self.start()

    def _callback(self, indata, frames, time_info, status) -> None:  # audio thread
        if status:
            # Overflows are normal under load; log once at debug level.
            log.debug("audio status: %s", status)
        block = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
        self._ring.append(block)
        if self._on_block is not None:
            try:
                self._on_block(block)
            except Exception as exc:
                log.error("audio consumer raised: %s", exc)

    def recent(self, seconds: float) -> np.ndarray:
        """Last N seconds from the ring - used for VAD pre-roll padding."""
        wanted = max(1, int(seconds * 1000 / BLOCK_MS))
        blocks = list(self._ring)[-wanted:]
        if not blocks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(blocks)
