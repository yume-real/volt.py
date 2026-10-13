"""Canonical non-public truth about the world."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .time import Time


@dataclass
class HiddenHistoryEntry:
    id: str = ""
    summary: str = ""
    facts: List[str] = field(default_factory=list)
    unaware_actor_ids: List[str] = field(default_factory=list)
    timestamp: Time = field(default_factory=Time)
    related_location_ids: List[str] = field(default_factory=list)
    related_actor_ids: List[str] = field(default_factory=list)
    flags: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "facts": list(self.facts),
            "unawareActorIds": list(self.unaware_actor_ids),
            "timestamp": self.timestamp.to_json(),
            "relatedLocationIds": list(self.related_location_ids),
            "relatedActorIds": list(self.related_actor_ids),
            "flags": dict(self.flags),
        }

    @classmethod
    def from_json(cls, json: Any) -> "HiddenHistoryEntry":
        data = json if isinstance(json, dict) else {}

        def strings(key: str) -> List[str]:
            raw = data.get(key)
            return [_text(item) for item in raw] if isinstance(raw, list) else []

        return cls(
            id=_text(data.get("id")),
            summary=_text(data.get("summary")),
            facts=strings("facts"),
            unaware_actor_ids=strings("unawareActorIds"),
            timestamp=Time.from_json(data.get("timestamp")),
            related_location_ids=strings("relatedLocationIds"),
            related_actor_ids=strings("relatedActorIds"),
            flags=dict(data.get("flags") or {}),
        )


def _text(value: Any) -> str:
    return "" if value is None else str(value)