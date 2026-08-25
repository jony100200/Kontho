<p align="center">
  <img src="Assets/Kontho Banner.png" alt="Kontho Banner" width="100%">
</p>

<p align="center">
  <strong>Universal Local Voice Typing for Windows — Bengali & English Code-Switching</strong>
  <br>
  Developed by <strong>Jony</strong> @ <strong>Kalponic Studio</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Studio-Kalponic%20Studio-E11D48?style=flat-square" alt="Kalponic Studio">
  <img src="https://img.shields.io/badge/Developer-Jony-blue?style=flat-square" alt="Jony">
  <img src="https://img.shields.io/badge/Privacy-100%25_Local-0078D4?style=flat-square" alt="100% Local">
  <img src="https://img.shields.io/badge/Languages-Bengali%20%2B%20English-2ea44f?style=flat-square" alt="Bengali + English">
  <img src="https://img.shields.io/badge/Engine-whisper.cpp-orange?style=flat-square" alt="whisper.cpp">
  <img src="https://img.shields.io/badge/Platform-Windows_10%20%2F%2011-blue?style=flat-square" alt="Windows 10/11">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">
</p>

---

## What is Kontho?

**Kontho** is a completely local, system-wide voice typing utility for Windows. Hold or press a hotkey anywhere, speak in **Bengali, English, or mixed Bengali-English technical speech**, and the dictated words appear instantly in whatever editor, input box, browser, or terminal currently holds focus.

- **100% Private & Local**: Zero audio and zero transcriptions ever leave your machine.
- **Focus Isolation**: The floating pill and system tray never steal focus or interrupt your active workflow.
- **Developer-Ready**: Automatically detects terminals (Windows Terminal, PowerShell, CMD, Git Bash, WezTerm) and forces literal lowercase command shaping without erroneous punctuation.
- **Bengali-English Mixed Speech**: Built on multilingual Whisper models that accurately preserve English technical vocabulary inside spoken Bengali sentences.
- **Safe Text Injection**: Paced Unicode keystrokes (`SendInput`) and clipboard paste with automated clipboard content preservation.

---

## Installation & Quick Start

### 1. Clone & Install Dependencies

```bat
git clone https://github.com/jony100200/Kontho.git
cd Kontho
pip install -r requirements.txt
```

### 2. Run Kontho

```bat
run_kontho.bat
```

*Or directly via Python:*

```bat
python -m kontho
```

On first launch, Kontho starts in the system tray and displays an unobtrusive floating pill. It automatically downloads the recommended **Whisper Small Q5_1** model (181 MiB) to `%LOCALAPPDATA%\Kontho\models`.

---

## Controls

| Action | Control |
|---|---|
| **Dictate** | **Hold or press hotkey** (`Ctrl + Shift + Space`, `F8`, etc.), speak, and release/press again. |
| **Click Floating Pill** | Single-click to start/stop listening. |
| **Open Settings** | Double-click or right-click the floating pill, or right-click the system tray icon. |
| **Move Floating Pill** | Click and drag the pill anywhere. It snaps cleanly to screen edges and remembers its position across reboots. |
| **Hide / Show Pill** | Left-click the system tray icon. |

---

## Key Settings

| Setting | Default | Purpose |
|---|---|---|
| **Model** | `Small Q5_1` | Balanced accuracy & speed. Switch to `Tiny Q5` for ultra-fast **0.2s** response time. |
| **Language** | `Bengali + English` | Multilingual recognition. Never uses `.en`-only checkpoints which drop Bengali. |
| **Device** | `CPU` | Leaves GPU VRAM free for game engines, 3D renderers, and image generation. GPU mode available. |
| **Threads** | Half CPU cores | Ensures dictation never starves concurrent builds or renders. |
| **Target Mode** | `Dynamic` | Text follows whichever window holds focus when you finish speaking. |
| **Insertion** | `Auto` | Paced Unicode typing or high-speed clipboard paste with automatic clipboard restoration. |
| **Logging** | **Off** | Your dictation is strictly private and never written to disk unless explicitly enabled. |

---

## Custom Vocabulary & Spoken Commands

Open **Settings → Vocabulary** to define custom domain terms or pronunciation replacements:
- Spoken: `"go dot"` → Written: `Godot`
- Spoken: `"pie side six"` → Written: `PySide6`
- Spoken: `"get status"` → Written: `git status`

Enable **Settings → Typing → Spoken punctuation** for voice macros like `"new line"` (`\n`), `"comma"` (`,`), or `"full stop"` (`.`).

---

## Model Benchmark Tool

Compare transcription latency, real-time factor (RTF), and accuracy across all installed models directly on your hardware:

```bat
python -m kontho.tools.benchmark --runs 3
```

To benchmark against a real recording:

```bat
python -m kontho.tools.benchmark --audio my_voice.wav --text
```

---

## Verification & Testing

```bat
python tests\test_smoke.py          # Fast offscreen imports & UI smoke tests
python tests\test_input_bridge.py   # Win32 SendInput 40-byte struct & UTF-16 tests
python tests\test_acceptance.py     # 10-point acceptance verification suite
pytest tests                        # Automated Pytest suite
```

### Record Voice Fixtures for Acceptance Tests:

```bat
python tests\record_test_voice.py --bn     # Record 5s Bengali sample (bn_sample.wav)
python tests\record_test_voice.py --mixed  # Record 5s Mixed sample (mixed_sample.wav)
```

---

## Author & Studio

<p align="center">
  <img src="Assets/Kalponic Studio Icon.png" alt="Kalponic Studio Logo" width="80">
  <br>
  <strong>Kalponic Studio</strong>
  <br>
  Lead Developer: <strong>Moinuddin Ahmed (Jony)</strong>
</p>

---

## Architecture & Standards

Kontho adheres strictly to the workspace engineering standards defined in `D:\KSAppDev\KS_ENGINEERING_STANDARD.md` and `D:\KSAppDev\Kontho\AGENTS.md`.

