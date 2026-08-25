"""Record real Bengali and mixed-language voice samples for acceptance tests.

Usage:
    python tests\\record_test_voice.py --bn       # Record Bengali sample
    python tests\\record_test_voice.py --mixed    # Record mixed Bengali+English sample
    python tests\\record_test_voice.py --all      # Record both sequentially
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

AUDIO_DIR = Path(__file__).resolve().parent / "audio"
SAMPLE_RATE = 16000


def record_sample(prompt: str, target_path: Path, duration_s: float = 5.0) -> bool:
    import sounddevice as sd

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print(f"Target file: {target_path.name}")
    print(f"Prompt: \"{prompt}\"")
    print("=" * 60)
    print("Recording starts in:")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1.0)

    print("\n  >>> RECORDING NOW - Speak clearly! <<<")
    try:
        recording = sd.rec(
            int(duration_s * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
        )
        sd.wait()
        print("  >>> Recording finished. <<<\n")
    except Exception as exc:
        print(f"Error capturing audio: {exc}")
        return False

    data = np.asarray(recording, dtype=np.int16).reshape(-1)
    # Check if there is actual audio above noise
    rms = float(np.sqrt(np.mean(np.square(data.astype(np.float32)))))
    if rms < 100:
        print(f"Warning: Low audio level detected (RMS={rms:.1f}). Check your microphone.")

    with wave.open(str(target_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(data.tobytes())

    print(f"Saved {len(data)/SAMPLE_RATE:.1f}s sample to: {target_path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Record test audio for Kontho acceptance tests.")
    parser.add_argument("--bn", action="store_true", help="Record Bengali test sample (bn_sample.wav)")
    parser.add_argument("--mixed", action="store_true", help="Record Mixed Bengali+English test sample (mixed_sample.wav)")
    parser.add_argument("--all", action="store_true", help="Record both samples sequentially")
    parser.add_argument("--seconds", type=float, default=5.0, help="Duration in seconds (default: 5.0)")
    args = parser.parse_args()

    if not (args.bn or args.mixed or args.all):
        parser.print_help()
        print("\nSpecify --bn, --mixed, or --all to record.")
        return 0

    if args.bn or args.all:
        prompt = "আমি বাংলায় ভয়েস টাইপিং টেস্ট করছি এবং কনথো সফটওয়্যার পরীক্ষা করছি।"
        record_sample(prompt, AUDIO_DIR / "bn_sample.wav", duration_s=args.seconds)

    if args.mixed or args.all:
        prompt = "আমি git commit করেছি database এ এবং API server deploy করেছি।"
        record_sample(prompt, AUDIO_DIR / "mixed_sample.wav", duration_s=args.seconds)

    print("\nAudio fixtures recorded successfully. You can now re-run acceptance tests:")
    print("  python tests\\test_acceptance.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
