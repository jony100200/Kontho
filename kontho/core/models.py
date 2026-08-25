"""Central model registry.

Every model path in Kontho comes from here. Nothing else is allowed to hold a
filename, so switching models is a registry lookup rather than a code change.

Hard rule enforced in code, not just documented: a `.en` checkpoint is
English-only and is never selectable for a Bengali or mixed language mode.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .settings import LANG_BN, LANG_MIXED, models_dir

REGISTRY_SCHEMA = "kontho_model_registry.v1"


@dataclass
class ModelEntry:
    id: str
    display_name: str
    engine: str = "whispercpp"
    path: str = ""                       # empty => resolved by the engine's own store
    model_family: str = "whisper"
    quantization: str = ""
    languages: tuple[str, ...] = ("multilingual",)
    model_size: str = ""                 # human readable, e.g. "181 MiB"
    approx_bytes: int = 0
    preferred_device: str = "cpu"
    code_switch_capable: bool = True
    source: str = "whisper.cpp"
    checksum: str = ""
    installed: bool = False
    experimental: bool = False
    notes: str = ""

    @property
    def english_only(self) -> bool:
        """`.en` Whisper checkpoints cannot produce Bengali."""
        return self.id.endswith(".en") or ".en-" in self.id or "english_only" in self.languages

    def supports_language(self, language: str) -> bool:
        if language in (LANG_BN, LANG_MIXED):
            return not self.english_only
        return True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["languages"] = list(self.languages)
        data["english_only"] = self.english_only
        return data


# The three presets the product ships with. Sizes are the published whisper.cpp
# figures; `installed` is decided at runtime, never assumed.
PRESETS: tuple[ModelEntry, ...] = (
    ModelEntry(
        id="tiny-q5_1",
        display_name="Tiny Q5 — Ultra Light",
        quantization="q5_1",
        model_size="31 MiB",
        approx_bytes=31 * 1024 * 1024,
        notes="Very low resource. Least accurate of the three.",
    ),
    ModelEntry(
        id="base-q5_1",
        display_name="Base Q5 — Light",
        quantization="q5_1",
        model_size="57 MiB",
        approx_bytes=57 * 1024 * 1024,
        notes="Low-resource everyday mode.",
    ),
    ModelEntry(
        id="small-q5_1",
        display_name="Small Q5 — Recommended",
        quantization="q5_1",
        model_size="181 MiB",
        approx_bytes=181 * 1024 * 1024,
        notes="Default. Accuracy is worth more than the 124 MiB saved.",
    ),
)

DEFAULT_MODEL_ID = "small-q5_1"


class ModelRegistry:
    """Presets plus user-added local models, persisted beside the models."""

    def __init__(self, directory: Path | None = None):
        self._dir = directory or models_dir()
        self._file = self._dir / "registry.json"
        self._lock = threading.RLock()
        self._custom: dict[str, ModelEntry] = {}
        self._load_custom()

    # -- listing -----------------------------------------------------------

    def all(self) -> list[ModelEntry]:
        with self._lock:
            rows = [self._with_state(e) for e in PRESETS]
            rows += [self._with_state(e) for e in self._custom.values()]
            return rows

    def for_language(self, language: str) -> list[ModelEntry]:
        """Only models that can actually produce the requested language."""
        return [m for m in self.all() if m.supports_language(language)]

    def get(self, model_id: str) -> ModelEntry | None:
        return next((m for m in self.all() if m.id == model_id), None)

    def resolve(self, model_id: str, language: str) -> ModelEntry:
        """Pick a usable model, refusing silently-wrong choices.

        If the requested model cannot speak the requested language we fall
        back to the default multilingual one and say so, rather than emitting
        English for Bengali speech.
        """
        entry = self.get(model_id)
        if entry is None:
            entry = self.get(DEFAULT_MODEL_ID)
        if entry is not None and not entry.supports_language(language):
            replacement = self.get(DEFAULT_MODEL_ID)
            if replacement is not None:
                replacement.notes = (
                    f"'{entry.display_name}' is English-only and cannot transcribe "
                    f"{language}; using {replacement.display_name}."
                )
                return replacement
        if entry is None:
            raise LookupError(f"no model registered for id {model_id!r}")
        return entry

    # -- installation state ------------------------------------------------

    def local_path(self, entry: ModelEntry) -> Path:
        if entry.path:
            return Path(entry.path)
        return self._dir / f"ggml-{entry.id}.bin"

    def is_installed(self, entry: ModelEntry) -> bool:
        path = self.local_path(entry)
        if path.is_file() and path.stat().st_size > 1024:
            return True
        # pywhispercpp keeps its own store; a model there counts as installed.
        try:
            from pywhispercpp.constants import MODELS_DIR

            alt = Path(MODELS_DIR) / f"ggml-{entry.id}.bin"
            return alt.is_file() and alt.stat().st_size > 1024
        except Exception:
            return False

    def _with_state(self, entry: ModelEntry) -> ModelEntry:
        clone = ModelEntry(**{**asdict(entry), "languages": tuple(entry.languages)})
        clone.installed = self.is_installed(entry)
        # Pin the concrete file. Handing the engine a bare id lets
        # pywhispercpp resolve it against its OWN store, which downloads a
        # second copy of every model and leaves this registry's install and
        # remove buttons controlling a file nothing actually loads.
        resolved = self.installed_path(entry)
        if resolved is not None:
            clone.path = str(resolved)
        return clone

    def installed_path(self, entry: ModelEntry) -> Path | None:
        path = self.local_path(entry)
        if path.is_file():
            return path
        try:
            from pywhispercpp.constants import MODELS_DIR

            alt = Path(MODELS_DIR) / f"ggml-{entry.id}.bin"
            if alt.is_file():
                return alt
        except Exception:
            pass
        return None

    # -- custom models -----------------------------------------------------

    def add_local(self, path: str | Path, display_name: str = "", *, experimental: bool = True) -> ModelEntry:
        src = Path(path).expanduser()
        if not src.is_file():
            raise FileNotFoundError(f"model file not found: {src}")
        entry = ModelEntry(
            id=f"custom:{src.stem}",
            display_name=display_name or f"{src.stem} (local)",
            path=str(src),
            quantization=_guess_quant(src.name),
            model_size=_human_size(src.stat().st_size),
            approx_bytes=src.stat().st_size,
            source="local file",
            experimental=experimental,
            notes="User-supplied model.",
        )
        with self._lock:
            self._custom[entry.id] = entry
            self._save_custom()
        return entry

    def remove(self, model_id: str, *, delete_file: bool = False) -> bool:
        with self._lock:
            entry = self._custom.pop(model_id, None)
            if entry is not None:
                self._save_custom()
                if delete_file and entry.path and Path(entry.path).is_file():
                    Path(entry.path).unlink(missing_ok=True)
                return True
        preset = next((e for e in PRESETS if e.id == model_id), None)
        if preset is None:
            return False
        path = self.installed_path(preset)
        if delete_file and path and path.is_file():
            path.unlink(missing_ok=True)
            return True
        return False

    # -- download ----------------------------------------------------------

    def download(self, model_id: str, progress: Callable[[int, int], None] | None = None) -> Path:
        """Fetch a preset. Verified by size, written atomically."""
        entry = self.get(model_id)
        if entry is None:
            raise LookupError(f"unknown model: {model_id}")
        existing = self.installed_path(entry)
        if existing is not None:
            return existing

        import urllib.request

        url = (
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
            f"ggml-{entry.id}.bin"
        )
        target = self.local_path(entry)
        tmp = target.with_suffix(".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or entry.approx_bytes or 0)
            done = 0
            with open(tmp, "wb") as handle:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if tmp.stat().st_size < 1024:
            tmp.unlink(missing_ok=True)
            raise IOError("downloaded model is implausibly small")
        tmp.replace(target)
        return target

    @staticmethod
    def checksum(path: str | Path, chunk: int = 1 << 20) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                block = handle.read(chunk)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()

    def open_folder(self) -> Path:
        return self._dir

    # -- persistence -------------------------------------------------------

    def _load_custom(self) -> None:
        if not self._file.is_file():
            return
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except Exception:
            return
        for row in raw.get("models", []):
            try:
                row["languages"] = tuple(row.get("languages") or ("multilingual",))
                row.pop("english_only", None)
                entry = ModelEntry(**row)
                self._custom[entry.id] = entry
            except Exception:
                continue

    def _save_custom(self) -> None:
        payload = {
            "schema": REGISTRY_SCHEMA,
            "models": [e.to_dict() for e in self._custom.values()],
        }
        tmp = self._file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._file)


def _guess_quant(name: str) -> str:
    lowered = name.lower()
    for tag in ("q5_1", "q5_0", "q8_0", "q4_k", "q4_0", "f16", "f32"):
        if tag in lowered:
            return tag
    return ""


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit != "GiB" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
