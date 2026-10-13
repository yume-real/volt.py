"""Typed, self-repairing configuration.

Every setting is described by a field spec (kind, range, locale label), which
drives the defaults, validation and the settings editor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from . import paths
from .logger import logger


@dataclass(frozen=True)
class Field:
    key: str
    kind: str  # int | ratio | text | bool | secret | choice | language
    default: Any
    label: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[str, ...] = ()


FIELDS: Tuple[Field, ...] = (
    Field("language", "language", "ru", "config.language"),
    Field("exitPhrase", "text", "exit", "config.exitPhrase"),
    Field("logRotation", "bool", True, "config.logRotation"),
    Field("logRotationLimit", "int", 1000, "config.logRotationLimit", minimum=100),
    Field("aiProvider", "choice", "aika", "config.aiProvider",
          choices=("aika", "custom")),
    Field("aikaApiKey", "secret", "", "config.aikaApiKey"),
    Field("aikaModel", "model", "gpt-4o-mini", "config.aikaModel"),
    Field("customProviderUrl", "text", "", "config.customProviderUrl"),
    Field("customProviderApiKey", "secret", "", "config.customProviderApiKey"),
    Field("customProviderModel", "model", "", "config.customProviderModel"),
    Field("temperature", "ratio", 0.7, "config.temperature",
          minimum=0.1, maximum=1.0),
    Field("messageHistorySize", "int", 30, "config.messageHistorySize", minimum=1),
    Field("worldHistorySize", "int", 50, "config.worldHistorySize", minimum=1),
    Field("worldEventsSize", "int", 50, "config.worldEventsSize", minimum=1),
    Field("worldRumorsSize", "int", 50, "config.worldRumorsSize", minimum=1),
    Field("actorMemorySize", "int", 20, "config.actorMemorySize", minimum=1),
    Field("actorKnowledgeSize", "int", 20, "config.actorKnowledgeSize", minimum=1),
    Field("textSpeed", "ratio", 0.5, "config.textSpeed",
          minimum=0.0, maximum=1.0),
    Field("generateLocalEvents", "bool", True, "config.generateLocalEvents"),
    Field("regenerateAttempts", "int", 1, "config.regenerateAttempts", minimum=0),
    Field("localEventInterval", "int", 300, "config.localEventInterval",
          minimum=30),
)

FIELDS_BY_KEY: Dict[str, Field] = {item.key: item for item in FIELDS}

# Settings of providers that are no longer offered. A key never carries over to
# a different provider, so these are dropped with a warning instead.
LEGACY_KEYS = ("mistralApiKey", "mistralModel")

AIKA_URL = "https://api.aika-ai.com/v1/chat/completions"

# Providers that publish a /models endpoint, so the model can be picked from a
# list instead of typed by hand.
MODEL_LISTING_PROVIDERS = ("aika",)


@dataclass
class Config:
    values: Dict[str, Any] = field(default_factory=dict)

    # -- construction -------------------------------------------------------

    @classmethod
    def defaults(cls) -> "Config":
        return cls({item.key: item.default for item in FIELDS})

    @classmethod
    def from_json(cls, raw: Any) -> "Config":
        config = cls.defaults()
        if not isinstance(raw, dict):
            logger.warning("Config root is not an object, using defaults")
            return config
        for key, value in raw.items():
            spec = FIELDS_BY_KEY.get(key)
            if spec is None:
                logger.warning(
                    "Setting '%s' is no longer used (%s) and was dropped"
                    % (key, "old provider" if key in LEGACY_KEYS else "unknown")
                )
                continue
            config.values[key] = coerce(spec, value, config.values[key])
        return config

    @classmethod
    def load(cls) -> "Config":
        try:
            # utf-8-sig tolerates a BOM, which editors like Notepad add.
            text = paths.CONFIG_PATH.read_text(encoding="utf-8-sig")
        except OSError:
            config = cls.defaults()
            config.save()
            return config
        try:
            config = cls.from_json(json.loads(text))
        except ValueError as error:
            logger.warning("Broken config -> %r, using defaults" % error)
            config = cls.defaults()
        config.save()
        return config

    def save(self) -> None:
        try:
            payload = json.dumps(self.to_json(), indent=4, ensure_ascii=False)
            paths.CONFIG_PATH.write_text(payload + "\n", encoding="utf-8")
        except OSError as error:
            logger.warning("Could not write config -> %r" % error)

    def to_json(self) -> Dict[str, Any]:
        return {item.key: self.values[item.key] for item in FIELDS}

    # -- access -------------------------------------------------------------

    def get(self, key: str) -> Any:
        spec = FIELDS_BY_KEY.get(key)
        if spec is None:
            raise KeyError(key)
        value = self.values.get(key, spec.default)
        return spec.default if value is None and spec.kind != "text" else value

    def get_text(self, key: str) -> str:
        value = self.get(key)
        return "" if value is None else str(value)

    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except (TypeError, ValueError):
            return int(FIELDS_BY_KEY[key].default)

    def get_bool(self, key: str) -> bool:
        value = self.get(key)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "y")

    def get_float(self, key: str) -> float:
        try:
            return float(self.get(key))
        except (TypeError, ValueError):
            return float(FIELDS_BY_KEY[key].default)

    def set(self, key: str, value: Any) -> Any:
        spec = FIELDS_BY_KEY[key]
        coerced = coerce(spec, value, self.values.get(key, spec.default))
        self.values[key] = coerced
        self.save()
        return coerced

    def reset(self) -> None:
        self.values = {item.key: item.default for item in FIELDS}
        self.save()

    # -- derived ------------------------------------------------------------

    @property
    def text_speed(self) -> float:
        return self.get_float("textSpeed")

    @property
    def provider(self) -> str:
        return self.get_text("aiProvider")

    def provider_endpoint(self) -> Tuple[str, str, str]:
        """Return ``(url, api_key, model)`` for the active provider."""
        if self.provider == "custom":
            return (
                self.get_text("customProviderUrl").strip(),
                self.get_text("customProviderApiKey").strip(),
                self.get_text("customProviderModel").strip(),
            )
        return (
            AIKA_URL,
            self.get_text("aikaApiKey").strip(),
            self.get_text("aikaModel").strip(),
        )

    @property
    def api_key(self) -> str:
        if self.provider == "custom":
            return self.get_text("customProviderApiKey").strip()
        return self.get_text("aikaApiKey").strip()

    def models_url(self) -> str:
        """URL of the ``/models`` endpoint derived from the completions URL."""
        url, _, _ = self.provider_endpoint()
        base = url.split("/v1/", 1)[0]
        return "%s/v1/models" % base if base else ""


def coerce(spec: Field, value: Any, fallback: Any) -> Any:
    """Coerce/validate a raw value against its field spec."""
    try:
        if spec.kind == "int":
            number = int(value)
            return _clamp(spec, number)
        if spec.kind == "ratio":
            return _clamp(spec, float(value))
        if spec.kind == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
        if spec.kind in ("text", "secret", "model"):
            return "" if value is None else str(value)
        if spec.kind == "choice":
            text = str(value).strip()
            return text if text in spec.choices else spec.default
        if spec.kind == "language":
            text = str(value).strip()
            return text or spec.default
    except (TypeError, ValueError):
        logger.warning("Broken value for '%s', using %r" % (spec.key, fallback))
        return fallback
    return fallback


def _clamp(spec: Field, number: float) -> Any:
    if spec.kind == "int":
        number = int(number)
    if spec.minimum is not None and number < spec.minimum:
        number = spec.minimum
    if spec.maximum is not None and number > spec.maximum:
        number = spec.maximum
    return number
