"""python -m kontho"""

from __future__ import annotations

import os
import sys

# Ensure standard streams are valid file objects under pythonw (GUI mode on Windows)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
if sys.stdin is None:
    sys.stdin = open(os.devnull, "r", encoding="utf-8")

from .ui.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
