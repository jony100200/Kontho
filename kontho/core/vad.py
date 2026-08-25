"""Voice activity detection and phrase segmentation.

Two jobs: skip silence so whisper is not asked to transcribe nothing, and cut
speech into phrases at natural pauses so text can be committed while the user
keeps talking.

The prototype used a bare `mean(|x|) > 0.006` with no padding, which clipped
first and last syllables. This keeps a pre-roll ring so a phrase starts
*before* detection fired, and a hangover so trailing consonants survive.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum

import numpy as np

log = logging.getLogger("kontho.vad")


class VadEvent(Enum):
    NONE = "none"
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"      # a phrase is ready to transcribe


@dataclass
class VadConfig:
    threshold: float = 0.012       # RMS over a block
    min_speech_ms: int = 250       # ignore coughs and clicks
    silence_ms: int = 600          # pause that finalises a phrase
    speech_pad_ms: int = 300       # pre-roll kept before speech was detected
    sample_rate: int = 16000
    block_ms: int = 32


class EnergyVad:
    """Adaptive energy VAD.

    The floor tracks background noise while nobody is speaking, so a noisy room
    raises the bar instead of transcribing hiss. Silero can replace this behind
    the same interface when whisper.cpp's VAD is wired up - the segmentation
    contract above it does not change.
    """

    def __init__(self, config: VadConfig | None = None):
        self.config = config or VadConfig()
        blocks_per_sec = 1000 / self.config.block_ms
        self._pad_blocks = max(1, int(self.config.speech_pad_ms / self.config.block_ms))
        self._silence_blocks = max(1, int(self.config.silence_ms / self.config.block_ms))
        self._min_speech_blocks = max(1, int(self.config.min_speech_ms / self.config.block_ms))
        self._preroll: deque[np.ndarray] = deque(maxlen=self._pad_blocks)
        self._phrase: list[np.ndarray] = []
        self._speaking = False
        self._silence_run = 0
        self._speech_run = 0
        self._noise_floor = self.config.threshold * 0.5
        self._blocks_per_sec = blocks_per_sec

    def reset(self) -> None:
        self._preroll.clear()
        self._phrase.clear()
        self._speaking = False
        self._silence_run = 0
        self._speech_run = 0

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def phrase_seconds(self) -> float:
        samples = sum(len(b) for b in self._phrase)
        return samples / float(self.config.sample_rate)

    def push(self, block: np.ndarray) -> VadEvent:
        """Feed one audio block; returns a segmentation event."""
        rms = float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0
        gate = max(self.config.threshold, self._noise_floor * 2.5)
        voiced = rms > gate

        if not self._speaking:
            self._preroll.append(block)
            if voiced:
                self._speech_run += 1
                if self._speech_run >= self._min_speech_blocks:
                    # Start the phrase from the pre-roll so the first syllable
                    # is not clipped off.
                    self._speaking = True
                    self._silence_run = 0
                    self._phrase = list(self._preroll)
                    self._preroll.clear()
                    return VadEvent.SPEECH_START
            else:
                self._speech_run = 0
                # Track the room only while it is quiet.
                self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms
            return VadEvent.NONE

        # Speaking: keep everything, including the trailing silence, so the
        # tail consonant is not cut.
        self._phrase.append(block)
        if voiced:
            self._silence_run = 0
        else:
            self._silence_run += 1
            if self._silence_run >= self._silence_blocks:
                self._speaking = False
                self._speech_run = 0
                return VadEvent.SPEECH_END
        return VadEvent.NONE

    def take_phrase(self) -> np.ndarray:
        """Consume the buffered phrase."""
        if not self._phrase:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._phrase)
        self._phrase = []
        self._silence_run = 0
        return audio

    def flush(self) -> np.ndarray:
        """Whatever is buffered right now - used when the user releases the key."""
        self._speaking = False
        self._speech_run = 0
        return self.take_phrase()

    def has_audio(self) -> bool:
        return bool(self._phrase)
