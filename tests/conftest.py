"""Pytest configuration and fixtures for Kontho test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kontho.core.models import ModelRegistry
from kontho.core.settings import SettingsStore
from kontho.core.stt import STTEngine, create_engine


@pytest.fixture(scope="session")
def engine() -> STTEngine:
    """Shared initialized STTEngine with installed model for transcription tests."""
    registry = ModelRegistry()
    default = registry.get(SettingsStore().value.model_id) or registry.get("base-q5_1")
    if not default or not registry.is_installed(default):
        default = next((registry.get(m) for m in ("base-q5_1", "small-q5_1", "tiny-q5_1")
                        if registry.is_installed(registry.get(m))), None)
    eng = create_engine("whispercpp")
    if default is not None:
        eng.load(default, device="cpu", threads=SettingsStore().value.threads)
    try:
        yield eng
    finally:
        eng.unload()
