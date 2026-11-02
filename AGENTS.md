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

## Shared agent rules (all agents: Claude, GPT/Codex, AGY, Grok, humans)

The owner set these rules once. They apply in every Kalponic repository.

1. **No AI attribution anywhere.** No `Co-Authored-By:`, `Claude-Session:`, "Generated with …" or similar trailers in commits, PRs, issues or code comments. The owner is the author. Credit for outside work goes only in `ACKNOWLEDGMENTS.md`.
2. **Stage explicit paths.** Never `git add .`, `git add -A` or a whole folder. Never commit secrets, local config or build output.
3. **One writer per checkout.** Never overwrite or commit another agent's uncommitted work. On a shared checkout, work in your own worktree. Fetch and rebase right before every push. No force pushes.
4. **Direct commits to `main` are fine** when the checkout is safe and tests pass. Ask first only before destructive or hard-to-undo steps.
5. **No machine-local details in shared output.** No absolute paths, host names, IPs, ports, user names or keys in code, docs or tests. Load them from config, env or discovery.
6. **Never install boot, auto-start or scheduled services.** Give the owner the start command instead.
7. **Models: poke before inference.** Check that the exact model is loaded before calling it. Never silently load, unload or swap a model, or touch a model another session is using.
8. **Evidence over claims.** Never report a test, benchmark, model readiness or release that was not actually run. Report failures with their output.
9. **Tests live where the repo says.** Pothik's tests live in `Pothik-Tests`. Cross-project suites live in `MasterTests`.
10. **Plain English** in docs, commits and reports. Keep them short.
