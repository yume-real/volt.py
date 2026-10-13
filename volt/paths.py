"""Filesystem layout.

Everything lives next to the package so that the app is portable: copy the
folder, run ``python Volt.py``, and config/saves/logs follow along.
"""

from __future__ import annotations

from pathlib import Path

PROGRAM_DIR = Path(__file__).resolve().parent.parent

CONFIG_PATH = PROGRAM_DIR / "config.json"
LOG_PATH = PROGRAM_DIR / "log.txt"

ASSETS_DIR = PROGRAM_DIR / "assets"
LOCALES_DIR = ASSETS_DIR / "locales"

SAVES_DIR = PROGRAM_DIR / "saves"
DEBUG_DIR = PROGRAM_DIR / "debug"

FALLBACK_LOCALE = "ru"


def ensure_dirs() -> None:
    # DEBUG_DIR is created on demand by the engine, only with VOLT_PY_DEBUG=1.
    SAVES_DIR.mkdir(parents=True, exist_ok=True)