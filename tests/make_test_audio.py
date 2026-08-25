"""Generate English test audio with Windows SAPI (offline, no network).

Gives the acceptance harness real speech to transcribe. Bengali is not
synthesizable here - this box has only en-US voices installed - so Bengali
accuracy has to be judged on a real recording.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "audio"

PHRASES = {
    "en_short": "Open the project folder.",
    "en_sentence": "This is a test of universal voice typing on Windows.",
    "en_technical": "Commit the changes to the git repository and push to origin.",
    "en_terminal": "git status",
}

_PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, `
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, `
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('{path}', $fmt)
$s.Rate = -1
$s.Speak('{text}')
$s.Dispose()
"""


def generate() -> dict[str, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made: dict[str, Path] = {}
    for name, text in PHRASES.items():
        path = OUT_DIR / f"{name}.wav"
        if not path.exists():
            script = _PS.format(path=str(path).replace("\\", "\\\\"),
                                text=text.replace("'", "''"))
            subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           check=True, capture_output=True)
        made[name] = path
    return made


if __name__ == "__main__":
    for name, path in generate().items():
        size = path.stat().st_size if path.exists() else 0
        print(f"{name:<14} {size/1024:>7.1f} KiB  {path}")
    if not OUT_DIR.exists():
        sys.exit(1)
