# Kontho V1 — verified status

**Date of verification: 2026-08-25.** Everything below was measured on this box
(Windows 11, 16-core CPU, RTX 4060 Ti 16 GB). Nothing here is remembered or
intended — where a claim has no measurement, it says so.

---

## What Kontho is

Press a hotkey anywhere → speak Bengali/English → the text goes wherever you
can type. Completely local: no audio and no transcription leaves the machine.

Core rule, enforced in `kontho/core/controller.py`: **window changes never
control the lifetime of microphone capture or STT.** Capture starts and stops
on the hotkey. The foreground window is not consulted until a phrase has
already been transcribed, and then only to decide where the text goes.

---

## Acceptance tests

Run with `python tests\test_acceptance.py`. Result on 2026-08-25: **8 pass,
0 fail, 2 need a recording of your voice.**

| # | Test | Result | Evidence |
|---|---|---|---|
| 1 | English dictation | **PASS** | 100% word match, RTF 0.39 → `'This is a test of universal voice typing on Windows.'` |
| 2 | Bengali dictation | **NEEDS YOU** | no Bengali SAPI voice on this box; see below |
| 3 | Bengali + English mixed | **NEEDS YOU** | same |
| 4 | Capture survives window change | **PASS** | 6 forced foreground changes during capture; `listening=True stream_running=True` |
| 5 | Dynamic targeting follows focus | **PASS** | target moved firefox.exe → explorer.exe, matched live foreground |
| 6 | Overlay does not steal focus | **PASS** | `WS_EX_NOACTIVATE=True WS_EX_TOOLWINDOW=True Qt.NoFocus=True foreground_unchanged=True` |
| 7 | Terminal receives text | **PASS** | `'Git status.'` → `'git status '`; literal profile forced for terminals |
| 8 | Model switch without restart | **PASS** | small 1022 MB → 556 MB, tiny 689 MB → 556 MB after unload; `engine.loaded=False` |
| 9 | CPU mode, no GPU allocation | **PASS** | VRAM 1745 MB → 1745 MB (delta +0 MB) |
| 10 | Settings persist across restart | **PASS** | fresh process read `base-q5_1|137|421|ctrl+shift+space` |

### The two tests that need you

Windows only has en-US voices installed here, so Bengali speech cannot be
synthesized for an automated test. Record two short 16 kHz wavs and re-run:

- `tests\audio\bn_sample.wav` — a plain Bengali sentence
- `tests\audio\mixed_sample.wav` — Bengali containing English technical words,
  e.g. *"আমি git commit করেছি database এ"*

Test 2 then asserts the output is ≥80% Bengali script (not romanised, not
translated). Test 3 asserts both scripts appear.

---

## Two real bugs found by testing, both fixed

### 1. Kontho could not type at all

`SendInput` returned "0 of 82 events sent" for every injection. The `INPUT`
struct was declared with a union containing only `KEYBDINPUT`, giving 32 bytes.
Windows x64 sizes that union by `MOUSEINPUT` and validates `cbSize` against the
real 40 — anything else is rejected outright, silently.

Fixed in `kontho/core/input_bridge.py` by declaring all three union members.
`sizeof(_INPUT)` is now 40. `GetLastError` is now reported on any refusal, so a
future block (e.g. UIPI error 5 against an elevated window) names itself.

### 2. Batched injection outruns the target and corrupts the text

With the struct fixed, text arrived with the right character *count* but a
mangled tail — `path: D:\KSAppDev 100% ।।।।।।।।।।।।` instead of the sentence.
The event array was verified correct in memory, so the corruption is the
target's message pump losing the race.

Measured against a real Notepad, **verified by reading the saved file from
disk** (`WM_GETTEXT` is unreliable on Win11 Notepad's `RichEditD2DPT` control
and reported corruption for text that was in fact correct — do not trust it):

| method | time | result |
|---|---|---|
| clipboard paste | 84 ms | correct |
| unicode, paced 12 ms | 703 ms | correct |
| unicode, paced 5 ms | 309 ms | **corrupted** |
| unicode, single burst | 3 ms | **corrupted** |

So clipboard is now the primary path — measurably both faster and reliable —
and direct typing is paced at 15 ms/char (12 ms was the threshold; 15 keeps a
margin), configurable in Settings → Typing.

The same race silently dropped accelerators: a batched Ctrl+S reported success
while Notepad stayed unsaved. `_press_ctrl_v` now sends one event at a time.

**Clipboard safety.** `auto` uses the clipboard only when it holds text, which
can be saved and put back. If it holds an image or a copied file — something
that cannot be reproduced — Kontho types instead rather than destroying it.
Restoration now happens in a `finally`, so a refused paste can no longer leave
dictated text sitting in your clipboard.

### Also fixed

Whisper annotates non-speech instead of returning nothing: silence becomes
`[BLANK_AUDIO]`, a fan becomes `(wind blowing)`, music becomes `[Music]`.
Those were being typed into the document. `strip_non_speech()` removes
annotation-only segments and cuts inline annotations out of real speech.
Bengali passes through untouched.

---

## Measured performance

Whisper Tiny Q5_1, CPU, 8 threads (of 16 cores):

- model load: 4.77 s
- transcription: 0.24 s for 3.0 s of audio — **RTF 0.08**

Whisper Small Q5_1 (the default) on real English speech: **RTF 0.39** — well
under 1.0, so transcription finishes faster than the speech took.

RAM, from Test 8: small-q5_1 peaked at 1022 MB resident and returned to 556 MB
after unload; tiny-q5_1 peaked at 689 MB. VRAM use is zero.

Run `python -m kontho.tools.benchmark --audio yourfile.wav` to compare every
installed model on the same audio. Without `--audio` it measures throughput on
a synthetic tone and says so — that number cannot judge accuracy.

---

## Deliberate decisions worth knowing

**The model loads at startup, not on first hotkey press.** This contradicts the
usual "never initialize models until needed" rule, and it is intentional: the
product promise is that pressing the hotkey works immediately, and a 5–15 s
load on first use would break it. The cost is ~550 MB resident while idle.
Switch to a smaller model if that matters on a given machine.

**CPU by default.** GPU is offered in Settings but off, so Kontho never
competes for VRAM with the image/video work on this box.

**Threads = half the cores** (8 of 16), so dictation coexists with a render
instead of starving it.

**No LLM anywhere in the path.** Text shaping is vocabulary, replacements and
per-profile rules — deterministic, and instant.

---

## Known gaps

- Tests 2 and 3 unverified pending a Bengali recording.
- `tests\test_live_insertion.py` proves insertion end-to-end but synthesizes
  real keystrokes and takes the foreground. It refuses to send anything unless
  its own Notepad has focus, but do not run it while working.
- Live insertion has been verified against Notepad only. Word, browsers and
  Windows Terminal are expected to work through the same two paths but have not
  been measured.
- GPU mode is exposed in Settings and untested.
- The overlay shows a live preview during listening; whisper.cpp is not a
  streaming engine, so the preview only updates when a phrase finalises.

---

## Layout

```
Kontho/
├── kontho/
│   ├── core/      settings, models, stt, audio, vad, hotkey,
│   │              target, input_bridge, text_shaping, controller, startup
│   ├── ui/        overlay, tray, settings_window, benchmark_window, app
│   └── tools/     benchmark
├── tests/         smoke, input_bridge, acceptance, live_insertion, make_test_audio
├── _Docs/         AUDIT_V1.md, V1_STATUS.md
└── run_kontho.bat
```

Models live in `%LOCALAPPDATA%\Kontho\models`, settings in
`%LOCALAPPDATA%\Kontho\settings.json`, diagnostics in
`%LOCALAPPDATA%\Kontho\kontho.log`. Dictated text is **not** logged unless you
turn on Settings → Advanced → "Log transcribed text".
