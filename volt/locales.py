"""Localisation: JSON files in ``assets/locales``.

The current locale falls back to :data:`volt.paths.FALLBACK_LOCALE` and then to
the key itself, so a missing translation never crashes the app.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from . import paths
from .logger import logger


class Locale:
    def __init__(self, name: str, entries: Dict[str, str]) -> None:
        self.name = name
        self.entries = entries

    @property
    def display_name(self) -> str:
        return self.entries.get("displayName", self.name)

    def get(self, key: str) -> Optional[str]:
        return self.entries.get(key)

    @staticmethod
    def available() -> List["Locale"]:
        result: List[Locale] = []
        try:
            files = sorted(paths.LOCALES_DIR.glob("*.json"))
        except OSError:
            files = []
        for path in files:
            locale = Locale.load(path.stem)
            if locale is not None:
                result.append(locale)
        return result

    @staticmethod
    def load(name: str) -> Optional["Locale"]:
        path = paths.LOCALES_DIR / ("%s.json" % name)
        try:
            # utf-8-sig tolerates a BOM, which editors like Notepad add.
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except OSError:
            logger.warning("Locale '%s' was not found" % name)
            return None
        except ValueError as error:
            logger.warning("Broken locale '%s' -> %r" % (name, error))
            return None
        entries = {
            key: value for key, value in raw.items() if isinstance(value, str)
        }
        return Locale(name, entries)


class Translator:
    """Holds the active locale plus the fallback one."""

    def __init__(self, name: str) -> None:
        self._fallback = Locale.load(paths.FALLBACK_LOCALE) or Locale(
            paths.FALLBACK_LOCALE, {}
        )
        self.load(name)

    def load(self, name: str) -> None:
        locale = Locale.load(name)
        if locale is None:
            locale = Locale(name, dict(self._fallback.entries))
            logger.warning("Falling back to locale '%s'" % self._fallback.name)
        self._current = locale
        self.language = name

    @property
    def locale(self) -> Locale:
        return self._current

    def t(self, key: str, fallback: str = "") -> str:
        value = self._current.get(key)
        if value is not None:
            return value
        value = self._fallback.get(key)
        if value is not None:
            return value
        if fallback:
            return fallback
        logger.warning("Missing locale entry '%s'" % key)
        return key

    def format(self, key: str, **values: object) -> str:
        template = self.t(key)
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            return template

    def error(self, key: str) -> str:
        return self.format("error.%s" % key)


_SIMPLE_ERROR_KEYS = {
    "providerUrlMissing": "provider.problem.url",
    "apiKeyMissing": "provider.problem.key",
    "modelMissing": "provider.problem.model",
    "authFailed": "provider.problem.auth",
    "emptyResponse": "provider.problem.empty",
}


def describe_generation_error(error: str) -> str:
    """Turn an :class:`volt.engine.GenerationResult` error into a sentence."""
    error = (error or "").strip()
    key = _SIMPLE_ERROR_KEYS.get(error)
    if key:
        return translator.t(key)
    for prefix, locale_key in (
        ("network:", "provider.problem.network"),
        ("badJson:", "provider.problem.badJson"),
        ("http", "provider.problem.http"),
        ("stream:", "provider.problem.http"),
    ):
        if error.startswith(prefix):
            reason = error[len(prefix):].strip(" :")
            if locale_key == "provider.problem.http" and reason.startswith(("4", "5")):
                reason = reason
            return translator.format(locale_key, reason=reason)
    return error or translator.t("game.failed")


translator = Translator(paths.FALLBACK_LOCALE)