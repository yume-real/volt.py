"""A conscious entity: the player, NPCs, animals, factions, gods, ships, AIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .needs import Needs
from .time import Time


@dataclass
class Actor:
    id: str = ""
    name: str = ""
    type: str = ""
    location_id: str = ""
    position: str = ""
    bio: str = ""
    traits: List[str] = field(default_factory=list)
    status: Dict[str, Any] = field(default_factory=dict)
    relationships: Dict[str, int] = field(default_factory=dict)
    needs: Needs = field(default_factory=Needs)
    memories: List[Dict[str, str]] = field(default_factory=list)
    knowledge: List[Dict[str, str]] = field(default_factory=list)
    birth_time: Time = field(default_factory=Time)
    death_time: Any = None
    inventory: List[Dict[str, str]] = field(default_factory=list)
    flags: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Allow building actors straight from raw dicts in tests and scripts.
        if isinstance(self.needs, dict):
            self.needs = Needs.from_json(self.needs)
        if isinstance(self.birth_time, dict):
            self.birth_time = Time.from_json(self.birth_time)
        if isinstance(self.death_time, dict):
            self.death_time = Time.from_json(self.death_time)

    # -- relations ----------------------------------------------------------

    def set_relationship(self, target_id: str, value: int) -> None:
        self.relationships.pop(target_id, None)
        self.relationships[target_id] = int(value)

    def change_relationship(self, target_id: str, delta: int) -> None:
        self.relationships[target_id] = self.relationships.get(target_id, 0) + int(delta)

    # -- status -------------------------------------------------------------

    def set_status(self, key: str, value: Any) -> None:
        if key == "age":
            return
        self.status[key] = value

    def remove_status(self, key: str) -> None:
        self.status.pop(key, None)

    def set_flag(self, key: str, value: Any) -> None:
        self.flags[key] = value

    def remove_flag(self, key: str) -> None:
        self.flags.pop(key, None)

    @property
    def is_dead(self) -> bool:
        return self.death_time is not None

    # -- bounded lists ------------------------------------------------------

    def add_memory(self, entry_id: str, content: str, limit: int) -> None:
        _add_entry(self.memories, entry_id, content, limit)

    def remove_memory(self, entry_id: str) -> None:
        _remove_entry(self.memories, entry_id)

    def add_knowledge(self, entry_id: str, content: str, limit: int) -> None:
        _add_entry(self.knowledge, entry_id, content, limit)

    def remove_knowledge(self, entry_id: str) -> None:
        _remove_entry(self.knowledge, entry_id)

    # -- inventory ----------------------------------------------------------

    def add_inventory_item(self, entry_id: str, item: str) -> None:
        self.inventory.append({"id": entry_id, "item": item})

    def remove_inventory_item(self, entry_id: str) -> None:
        self.inventory = [e for e in self.inventory if e.get("id") != entry_id]

    def modify(self, key: str, value: Any) -> "Actor":
        data = self.to_json()
        data[key] = value
        return Actor.from_json(data)

    # -- serialisation ------------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "locationId": self.location_id,
            "position": self.position,
            "bio": self.bio,
            "traits": list(self.traits),
            "status": dict(self.status),
            "relationships": dict(self.relationships),
            "needs": self.needs.to_json(),
            "memories": [dict(entry) for entry in self.memories],
            "knowledge": [dict(entry) for entry in self.knowledge],
            "birthTime": self.birth_time.to_json(),
            "deathTime": self.death_time.to_json() if self.death_time else None,
            "inventory": [dict(entry) for entry in self.inventory],
            "flags": dict(self.flags),
        }

    @classmethod
    def from_json(cls, json: Any) -> "Actor":
        data = json if isinstance(json, dict) else {}
        death = data.get("deathTime")
        return cls(
            id=_text(data.get("id")),
            name=_text(data.get("name")),
            type=_text(data.get("type")),
            location_id=_text(data.get("locationId")),
            position=_text(data.get("position")),
            bio=_text(data.get("bio")),
            traits=[_text(item) for item in data.get("traits") or []],
            status=dict(data.get("status") or {}),
            relationships=_int_map(data.get("relationships")),
            needs=Needs.from_json(data.get("needs")),
            memories=_entry_list(data.get("memories")),
            knowledge=_entry_list(data.get("knowledge")),
            birth_time=Time.from_json(data.get("birthTime")),
            death_time=Time.from_json(death) if death else None,
            inventory=_entry_list(data.get("inventory"), second_key="item"),
            flags=dict(data.get("flags") or {}),
        )


def _add_entry(entries: List[Dict[str, str]], entry_id: str, content: str,
               limit: int) -> None:
    if any(entry.get("id") == entry_id for entry in entries):
        return
    if len(entries) >= max(1, limit):
        entries.pop(0)
    entries.append({"id": entry_id, "content": content})


def _remove_entry(entries: List[Dict[str, str]], entry_id: str) -> None:
    entries[:] = [entry for entry in entries if entry.get("id") != entry_id]


def _int_map(raw: Any) -> Dict[str, int]:
    result: Dict[str, int] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                result[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    return result


def _entry_list(raw: Any, second_key: str = "content") -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        return []
    entries: List[Dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            entries.append(
                {
                    "id": _text(item.get("id")),
                    second_key: _text(item.get(second_key)),
                }
            )
    return entries


def _text(value: Any) -> str:
    return "" if value is None else str(value)