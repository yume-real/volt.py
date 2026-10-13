"""Chat transcript entry (player actions and narration)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ChatEntry:
    role: Role
    content: str
    id: int = 0

    def to_json(self) -> Dict[str, Any]:
        return {"id": self.id, "role": self.role.value, "content": self.content}

    @classmethod
    def from_json(cls, json: Any) -> "ChatEntry":
        data = json if isinstance(json, dict) else {}
        raw_role = _text(data.get("role")) or Role.ASSISTANT.value
        try:
            role = Role(raw_role)
        except ValueError:
            role = Role.ASSISTANT
        try:
            entry_id = int(data.get("id", 0) or 0)
        except (TypeError, ValueError):
            entry_id = 0
        return cls(role=role, content=_text(data.get("content")), id=entry_id)


def _text(value: Any) -> str:
    return "" if value is None else str(value)