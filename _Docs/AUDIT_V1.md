# Kontho V1 — audit of the supplied prototype

Audited before writing anything: `M:\KS Apps\KS-Studio\tools\voicedock.py` (152 lines).
Target `D:\KSAppDev\Kontho` was an empty git repo.

## What the prototype is

A **Linux CLI** dictation script: `sounddevice` → crude amplitude VAD →
`faster-whisper` (`base.en`) → `xdotool type`. Global hotkey via `pynput`,
toggle or push-to-talk, auto-stop on silence.

It works on its own terms. It is not a base Kontho can extend, because the two
things that make Kontho *Kontho* — Windows text injection and a focus-independent
floating UI — are exactly the parts that do not port.

## Reusable — kept

| Prototype idea | Where it lives in Kontho |
|---|---|
| Pipeline shape: mic → buffer → VAD → STT → inject | `core/` module split |
| 16 kHz mono int16 convention | `core/audio.py` |
| Push-to-talk **and** toggle from one hotkey | `core/hotkey.py`, `core/controller.py` |
| Mic selection by name substring | `core/audio.py` |
| Silence-based phrase finalisation | `core/vad.py` |
| Trailing space so consecutive dictations do not run together | `core/input_bridge.py` |

## Not reusable — and why

| Prototype | Problem | Kontho |
|---|---|---|
| `xdotool type` | Linux only | Win32 `SendInput` + `KEYEVENTF_UNICODE`, clipboard fallback |
| `faster-whisper` | Spec requires whisper.cpp | `pywhispercpp` behind an engine interface |
| `base.en` default | **`.en` is English-only** — breaks Bengali | `small-q5_1` multilingual default; `.en` refused by the registry |
| `abs(arr).mean() > 0.006` | Fixed threshold, no padding, clips syllables | Calibrated energy VAD with pre-roll padding and hangover |
| Transcribe whole utterance at the end | No preview, no streaming | Segment finalisation while recording continues |
| No UI / tray / settings / model manager / targeting | Absent | Built |
| Hard-coded model string | Spec forbids | Central `ModelRegistry` |

**Verdict: the design is sound, the code is ~0% portable.** Kontho is a new
Windows implementation that keeps the prototype's shape.

## Environment found (nothing needed building from source)

| Need | Found |
|---|---|
| whisper.cpp | **`pywhispercpp` already installed** in `D:\KSAppDev\.venv` — real whisper.cpp bindings, and it can fetch models |
| Spec models | `tiny-q5_1`, `base-q5_1`, `small-q5_1` all present in its catalogue (33 total) |
| Hotkeys / focus / injection / clipboard | `pywin32` already installed |
| numpy / soundfile / requests | already installed |
| UI | PySide6 **installed for this task** (6.11.2) |
| Audio capture | sounddevice **installed for this task** (0.5.6), 13 input devices visible |

One venv at the root, per the standing rule. No CUDA required; CPU is the default path.

## Consequence for V1

Because whisper.cpp bindings and the Win32 layer were already present, V1 is
assembly plus the missing architecture — not a port. The parts that had to be
written from nothing are the ones the prototype never had: model registry,
target manager, input bridge, floating no-activation overlay, tray, settings,
profiles, vocabulary, and the benchmark tool.
