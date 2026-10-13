"""Save files.

A save is a single pretty-printed JSON file named ``{world_id}_{timestamp}.json``
inside :data:`volt.paths.SAVES_DIR`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import paths
from .logger import logger
from .models import World

INVALID_ID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class SaveInfo:
    path: Path
    world_id: str
    world_name: str
    modified: datetime

    @property
    def title(self) -> str:
        return self.world_name or self.world_id or self.path.stem


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d+%H-%M-%S")


def file_name_for(world_id: str) -> str:
    return "%s_%s.json" % (sanitize_id(world_id), timestamp())


def sanitize_id(world_id: str) -> str:
    cleaned = INVALID_ID_CHARS.sub("", (world_id or "").strip())
    return cleaned or "world"


def list_saves() -> List[SaveInfo]:
    try:
        paths.SAVES_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(paths.SAVES_DIR.glob("*.json"))
    except OSError as error:
        logger.warning("Could not list saves -> %r" % error)
        return []

    saves: List[SaveInfo] = []
    for path in files:
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            modified = datetime.now()
        world_id = _id_from_name(path.stem)
        world_name = ""
        data = _read_json(path)
        if isinstance(data, dict):
            world_id = str(data.get("id") or world_id)
            world_name = str(data.get("name") or "")
        saves.append(SaveInfo(path, world_id, world_name, modified))
    saves.sort(key=lambda item: item.modified, reverse=True)
    return saves


def load_world(path: Path) -> Optional[World]:
    data = _read_json(Path(path))
    if not isinstance(data, dict):
        return None
    world = World.from_json(data)
    world.save_path = Path(path)
    return world


def delete_save(path: Path) -> bool:
    try:
        Path(path).unlink()
        return True
    except OSError as error:
        logger.warning("Could not delete '%s' -> %r" % (path, error))
        return False


def duplicate(world: World) -> Path:
    """Write a copy of ``world`` under a fresh file name."""
    clone = world.copy()
    clone.id = "%s_copy" % sanitize_id(world.id or "world")
    target = paths.SAVES_DIR / file_name_for(clone.id)
    clone.save_path = target
    clone.write()
    return target


def _id_from_name(stem: str) -> str:
    # "{id}_{YYYY-MM-DD+HH-MM-SS}" -> id
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and re.match(r"^\d{4}-\d{2}-\d{2}", parts[1]):
        return parts[0]
    return stem


def _read_json(path: Path) -> Optional[object]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        logger.warning("Could not read '%s' -> %r" % (path, error))
        return None
    try:
        return json.loads(text)
    except ValueError as error:
        logger.warning("Broken save '%s' -> %r" % (path, error))
        return None