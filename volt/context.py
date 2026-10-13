"""Process-wide access to the active configuration.

Lets model code read settings without plumbing a config object through every
call.
"""

from __future__ import annotations

from typing import Optional

from .config import Config

_config: Optional[Config] = None


def set_config(config: Config) -> None:
    global _config
    _config = config


def config() -> Config:
    return _config if _config is not None else Config.defaults()


def cfg_int(key: str) -> int:
    return config().get_int(key)
