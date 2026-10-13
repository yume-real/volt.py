"""Actor needs (0..100, higher means worse) plus free-form custom needs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

STANDARD_NEEDS = (
    "hunger",
    "thirst",
    "exhaustion",
    "stress",
    "comfort",
    "boredom",
    "loneliness",
    "hygiene",
)

OTHER_PREFIX = "other."


@dataclass
class Needs:
    hunger: int = 0
    thirst: int = 0
    exhaustion: int = 0
    stress: int = 0
    comfort: int = 0
    boredom: int = 0
    loneliness: int = 0
    hygiene: int = 0
    other: Dict[str, int] = field(default_factory=dict)

    def change(self, need: str, value: int, delta: bool = False) -> "Needs":
        """Update one need. ``other.foo`` addresses a custom need."""
        if need.startswith(OTHER_PREFIX):
            name = need[len(OTHER_PREFIX):]
            current = self.other.get(name, 0)
            new_value = current + value if delta else value
            other = dict(self.other)
            other[name] = _clamp(new_value)
            return Needs(**{**_standard_dict(self), "other": other})

        data = self.to_json()
        if need not in STANDARD_NEEDS:
            return self
        current = int(data.get(need, 0) or 0)
        new_value = current + value if delta else value
        data[need] = _clamp(new_value)
        return Needs.from_json(data)

    def as_dict(self) -> Dict[str, int]:
        data = {name: getattr(self, name) for name in STANDARD_NEEDS}
        data.update(self.other)
        return data

    def to_json(self) -> Dict[str, Any]:
        return {name: getattr(self, name) for name in STANDARD_NEEDS} | {
            "other": dict(self.other)
        }

    @classmethod
    def from_json(cls, json: Any) -> "Needs":
        data = json if isinstance(json, dict) else {}
        other_raw = data.get("other")
        other: Dict[str, int] = {}
        if isinstance(other_raw, dict):
            for key, value in other_raw.items():
                try:
                    other[str(key)] = int(value)
                except (TypeError, ValueError):
                    other[str(key)] = 0
        kwargs: Dict[str, Any] = {}
        for name in STANDARD_NEEDS:
            try:
                kwargs[name] = _clamp(int(data.get(name, 0) or 0))
            except (TypeError, ValueError):
                kwargs[name] = 0
        kwargs["other"] = other
        return cls(**kwargs)


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))


def _standard_dict(needs: "Needs") -> Dict[str, Any]:
    return {name: getattr(needs, name) for name in STANDARD_NEEDS}