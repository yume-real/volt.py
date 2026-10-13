"""A place in the world."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Location:
    id: str = ""
    name: str = ""
    description: str = ""
    status: str = ""
    connected_location_ids: List[str] = field(default_factory=list)
    environment_and_items: Dict[str, str] = field(default_factory=dict)
    flags: Dict[str, Any] = field(default_factory=dict)

    @property
    def area(self) -> str:
        """``loc_apartment_kitchen`` -> ``apartment``."""
        stripped = self.id[4:] if self.id.startswith("loc_") else self.id
        return stripped.split("_")[0] if stripped else self.id

    def add_connection(self, location_id: str) -> None:
        if location_id not in self.connected_location_ids:
            self.connected_location_ids.append(location_id)

    def remove_connection(self, location_id: str) -> None:
        if location_id in self.connected_location_ids:
            self.connected_location_ids.remove(location_id)

    def set_flag(self, key: str, value: Any) -> None:
        self.flags[key] = value

    def remove_flag(self, key: str) -> None:
        self.flags.pop(key, None)

    def set_environment_item(self, key: str, value: str) -> None:
        self.environment_and_items[key] = value

    def remove_environment_item(self, key: str) -> None:
        self.environment_and_items.pop(key, None)

    def modify(self, key: str, value: Any) -> "Location":
        data = self.to_json()
        data[key] = value
        return Location.from_json(data)

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "connectedLocationIds": list(self.connected_location_ids),
            "environmentAndItems": dict(self.environment_and_items),
            "flags": dict(self.flags),
        }

    @classmethod
    def from_json(cls, json: Any) -> "Location":
        data = json if isinstance(json, dict) else {}
        connections = data.get("connectedLocationIds")
        environment = data.get("environmentAndItems")
        flags = data.get("flags")
        return cls(
            id=_text(data.get("id")),
            name=_text(data.get("name")),
            description=_text(data.get("description")),
            status=_text(data.get("status")),
            connected_location_ids=[_text(item) for item in connections or []],
            environment_and_items={
                _text(key): _text(value)
                for key, value in (environment or {}).items()
            }
            if isinstance(environment, dict)
            else {},
            flags=dict(flags) if isinstance(flags, dict) else {},
        )


def _text(value: Any) -> str:
    return "" if value is None else str(value)