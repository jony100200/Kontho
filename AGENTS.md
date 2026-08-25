# Kontho — Universal Local Voice Typing for Windows

## Purpose

Kontho provides universal, completely local push-to-talk and toggle voice typing for Windows, specialized for Bengali and English code-switching and technical developer workflows.

## Standards and Authority

- Follow the single workspace canonical engineering standard at `D:\KSAppDev\KS_ENGINEERING_STANDARD.md`.
- Follow the root DOX framework at `D:\KSAppDev\AGENTS.md`.

## Architectural Invariants

1. **Capture Independence**: Window changes must never control the lifetime of microphone capture or STT. Capture is started and stopped exclusively by the hotkey. The foreground target is queried only to determine text delivery.
2. **Zero Cloud / Total Privacy**: Dictated audio and transcriptions never leave the local machine. Dictated text is never logged to disk unless explicitly enabled by the user in Settings.
3. **Focus Isolation**: The floating overlay pill and any background helpers must NEVER steal keyboard focus. Overlay uses `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | Qt.NoFocus` to ensure typed text always lands in the target window.
4. **Paced Unicode & Clipboard Safety**: Text injection defaults to paced Unicode `SendInput` (≥12ms per character) or clipboard paste when safe. If the clipboard contains unrestorable data (images, files), Unicode typing is forced to prevent data loss. The previous clipboard content is always restored after paste.
5. **Deterministic Text Shaping**: No LLM in the typing path. All text transformations (vocabulary corrections, spoken punctuation commands, shell formatting) are rule-based, deterministic, and instant.
6. **Resource Discipline**: STT defaults to CPU with half the machine's cores to prevent VRAM and compute starvation for 3D/AI workloads. Switching models must explicitly unload and garbage-collect the previous model before loading the next.

## Directory Structure

- `kontho/core/`: Settings, model registry, audio capture, VAD segmentation, STT engine, hotkey listener, target manager, text shaping, input bridge, startup registration, controller.
- `kontho/ui/`: Floating overlay pill, system tray icon, settings window, benchmark window, application shell.
- `kontho/tools/`: Benchmarking CLI tool.
- `tests/`: Smoke tests, unit tests, acceptance tests, live insertion verification, audio fixtures.
- `Assets/`: High-resolution icons and banners.
- `_Docs/`: Architectural audit, verification logs, and status records.

## Verification

- `python tests\test_smoke.py`: Offscreen smoke tests verifying imports and component initialization.
- `python tests\test_input_bridge.py`: Win32 struct validation and injection logic tests.
- `python tests\test_acceptance.py`: 10-point V1 acceptance test suite.
- `pytest tests`: Pytest automated suite for continuous verification.
- `python -m kontho.tools.benchmark`: Benchmark comparing all installed models on real audio.
