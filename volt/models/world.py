"""The world: everything the LLM may read or mutate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import paths
from ..context import cfg_int
from ..logger import logger
from .actor import Actor
from .chat_entry import ChatEntry, Role
from .hidden_history import HiddenHistoryEntry
from .location import Location
from .time import Time

PREPROCESSED_STATES = ("addLocation", "addActor", "updateActor")

_STATE_HANDLERS: Dict[str, Callable[["World", Dict[str, Any]], None]] = {}


class World:
    def __init__(
        self,
        id: str = "",
        name: str = "",
        current_time: Optional[Time] = None,
        setting_summary: str = "",
        locations: Optional[List[Location]] = None,
        actors: Optional[List[Actor]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        current_events: Optional[List[Dict[str, str]]] = None,
        current_rumors: Optional[List[Dict[str, str]]] = None,
        hidden_history: Optional[List[HiddenHistoryEntry]] = None,
        message_history: Optional[List[ChatEntry]] = None,
        global_flags: Optional[Dict[str, Any]] = None,
        save_path: Optional[Path] = None,
    ) -> None:
        self.id = id
        self.name = name
        self.current_time = current_time or Time()
        self.setting_summary = setting_summary
        self.locations = locations if locations is not None else []
        self.actors = actors if actors is not None else []
        self.history = history if history is not None else []
        self.current_events = current_events if current_events is not None else []
        self.current_rumors = current_rumors if current_rumors is not None else []
        self.hidden_history = (
            hidden_history if hidden_history is not None else []
        )
        self.message_history = message_history if message_history is not None else []
        self.global_flags = global_flags if global_flags is not None else {}

        self._new_day = False
        self._current_narration: Optional[str] = None
        self._save_path = save_path

    # -- identity -----------------------------------------------------------

    @property
    def save_path(self) -> Path:
        if self._save_path is not None:
            return self._save_path
        return paths.SAVES_DIR / ("%s.json" % (self.id or "world"))

    @save_path.setter
    def save_path(self, value: Optional[Path]) -> None:
        if value is None:
            self._save_path = None
        elif str(value).endswith(".json"):
            self._save_path = Path(value)

    @property
    def new_day(self) -> bool:
        """True once after the calendar day rolls over."""
        value = self._new_day
        self._new_day = False
        return value

    def copy(self) -> "World":
        clone = World.from_json(self.to_json())
        clone.save_path = self._save_path
        return clone

    # -- time ---------------------------------------------------------------

    def advance_time(self, seconds: int) -> None:
        current_day = self.current_time.day
        self.current_time = self.current_time.add_seconds(seconds)

        if self.current_time.day != current_day:
            self._new_day = True

        for actor in self.actors:
            birthday = (
                actor.birth_time.month == self.current_time.month
                and actor.birth_time.day == self.current_time.day
            )
            actor.set_status("isBirthday", birthday)

    def parse_seconds_from_advance_time(self, state: Dict[str, Any]) -> Optional[int]:
        if state.get("type") != "advanceTime":
            return None

        def count(key: str) -> int:
            try:
                return int(state.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0

        return (
            count("years") * self.current_time.days_in_year * 3600
            + count("months") * self.current_time.days_in_month * 3600
            + count("days") * self.current_time.hours_in_day * 3600
            + count("hours") * 3600
            + count("minutes") * 60
            + count("seconds")
        )

    # -- narration ----------------------------------------------------------

    def get_current_narration(self) -> str:
        text = self._current_narration or ""
        self._current_narration = None
        return text

    # -- bounded lists ------------------------------------------------------

    def add_message_to_history(self, role: Role, content: str) -> None:
        limit = cfg_int("messageHistorySize")
        if len(self.message_history) > max(1, limit):
            self.message_history.pop(0)

        next_id = 1
        for entry in reversed(self.message_history):
            if entry.role is role:
                next_id = entry.id + 1
                break
        self.message_history.append(ChatEntry(role=role, content=content, id=next_id))

    def _append_limited(self, entries: List[Dict[str, str]], key: str,
                        entry_id: str, content: str, limit_key: str) -> None:
        if not entry_id or not content:
            return
        # Re-using an id updates the entry in place: the prompts ask the model to
        # keep one stable aggregate entry instead of numbered duplicates.
        for index, entry in enumerate(entries):
            if entry.get("id") == entry_id:
                entries[index] = {"id": entry_id, "content": content}
                return
        limit = max(1, cfg_int(limit_key))
        if len(entries) > limit:
            entries.pop(0)
        entries.append({"id": entry_id, "content": content})

    def add_history_entry(self, entry_id: str, content: str) -> None:
        self._append_limited(self.history, "history", entry_id, content,
                             "worldHistorySize")

    def remove_history_entry(self, entry_id: str) -> None:
        self.history[:] = [e for e in self.history if e.get("id") != entry_id]

    def add_event_entry(self, entry_id: str, content: str) -> None:
        self._append_limited(self.current_events, "currentEvents", entry_id,
                             content, "worldEventsSize")

    def remove_event_entry(self, entry_id: str) -> None:
        self.current_events[:] = [
            e for e in self.current_events if e.get("id") != entry_id
        ]

    def add_rumor_entry(self, entry_id: str, content: str) -> None:
        self._append_limited(self.current_rumors, "currentRumors", entry_id,
                             content, "worldRumorsSize")

    def remove_rumor_entry(self, entry_id: str) -> None:
        self.current_rumors[:] = [
            e for e in self.current_rumors if e.get("id") != entry_id
        ]

    # -- lookups ------------------------------------------------------------

    def location_exists(self, location_id: str) -> bool:
        return any(location.id == location_id for location in self.locations)

    def get_location(self, location_id: str) -> Optional[Location]:
        for location in self.locations:
            if location.id == location_id:
                return location
        return None

    def get_connected_locations(self, location_id: str) -> List[Location]:
        location = self.get_location(location_id)
        if location is None:
            return []
        return [
            found
            for found in (self.get_location(cid) for cid in location.connected_location_ids)
            if found is not None
        ]

    def get_locations_in_area(self, location: Location) -> List[Location]:
        return [
            other
            for other in self.locations
            if other.area == location.area and other.id != location.id
        ]

    def actor_exists(self, actor_id: str) -> bool:
        return any(actor.id == actor_id for actor in self.actors)

    def get_actor(self, actor_id: str) -> Optional[Actor]:
        for actor in self.actors:
            if actor.id == actor_id:
                return actor
        return None

    def get_actors_in_area(self, area: str, exclude_id: str = "") -> List[Actor]:
        return [
            actor
            for actor in self.actors
            if actor.location_id.startswith("loc_" + area)
            and actor.id != exclude_id
        ]

    def modify_actor_if_exists(self, actor_id: str, key: str, value: Any) -> None:
        actor = self.get_actor(actor_id)
        if actor is None:
            return
        modified = actor.modify(key, value)
        self.actors[self.actors.index(actor)] = modified

    def modify_location_if_exists(self, location_id: str, key: str,
                                  value: Any) -> None:
        location = self.get_location(location_id)
        if location is None:
            return
        self.locations[self.locations.index(location)] = location.modify(key, value)

    @property
    def player_actor(self) -> Optional[Actor]:
        for actor in self.actors:
            if actor.status.get("role") == "player" or "player" in actor.status.values():
                return actor
        for actor in self.actors:
            if actor.id == "actor_player":
                return actor
        return None

    @property
    def areas(self) -> List[str]:
        seen: List[str] = []
        for location in self.locations:
            if location.area not in seen:
                seen.append(location.area)
        return seen

    def get_recent_narration(self, count: int = 7) -> List[str]:
        messages = [
            entry.content for entry in self.message_history
            if entry.role is Role.ASSISTANT
        ]
        return list(reversed(messages[-count:]))

    # -- global flags / hidden history --------------------------------------

    def set_global_flag(self, key: str, value: Any) -> None:
        self.global_flags[key] = value

    def remove_global_flag(self, key: str) -> None:
        self.global_flags.pop(key, None)

    def add_hidden_history(self, entry: HiddenHistoryEntry) -> None:
        if entry.id and not any(h.id == entry.id for h in self.hidden_history):
            self.hidden_history.append(entry)

    def update_hidden_history(self, entry: HiddenHistoryEntry) -> None:
        for index, existing in enumerate(self.hidden_history):
            if existing.id == entry.id:
                self.hidden_history[index] = entry
                return

    def remove_hidden_history(self, entry_id: str) -> None:
        self.hidden_history[:] = [h for h in self.hidden_history
                                  if h.id != entry_id]

    # -- prompts context ----------------------------------------------------

    def to_player_action_info(self, command: str = "") -> Dict[str, Any]:
        player = self.player_actor
        if player is None:
            logger.warning("World '%s' has no player actor" % self.id)
            return {"settingSummary": self.setting_summary,
                    "time": self.current_time.to_json(),
                    "playerCommand": command}

        location = self.get_location(player.location_id)
        info: Dict[str, Any] = {
            "settingSummary": self.setting_summary,
            "time": self.current_time.to_json(),
            "player": player.to_json(),
            "playerCommand": command,
            "globalFlags": dict(self.global_flags),
            "recentNarration": self.get_recent_narration(),
        }
        if location is None:
            info["currentLocation"] = None
            info["connectedLocations"] = []
            info["nearbyActors"] = []
        else:
            info["currentLocation"] = location.to_json()
            info["connectedLocations"] = [
                other.to_json() for other in self.get_locations_in_area(location)
            ]
            info["nearbyActors"] = [
                actor.to_json()
                for actor in self.get_actors_in_area(location.area, player.id)
            ]

        info["recentHistory"] = _tail(self.history, 20)
        info["hiddenHistory"] = [entry.to_json() for entry in self.hidden_history]
        info["currentEvents"] = _tail(self.current_events, 10)
        info["currentRumors"] = _tail(self.current_rumors, 10)
        info["takenActorIds"] = [actor.id for actor in self.actors]
        info["takenLocationIds"] = [location.id for location in self.locations]
        info["existingAreas"] = self.areas
        return info

    def to_event_info(self) -> Dict[str, Any]:
        player = self.player_actor
        if player is None:
            logger.warning("World '%s' has no player actor" % self.id)
            return {"settingSummary": self.setting_summary,
                    "time": self.current_time.to_json()}

        location = self.get_location(player.location_id)
        if location is None:
            nearby_locations: List[Location] = []
            actors: List[Actor] = []
            area = ""
        else:
            nearby_locations = self.get_locations_in_area(location)
            area = location.area
            actors = self.get_actors_in_area(area)

        actor_ids = [actor.id for actor in actors]
        return {
            "settingSummary": self.setting_summary,
            "time": self.current_time.to_json(),
            "centerLocationId": player.location_id,
            "locations": [item.to_json() for item in nearby_locations],
            "actors": [actor.to_json() for actor in actors],
            "recentHistory": _tail(self.history, 20),
            "hiddenHistory": [
                entry.to_json()
                for entry in self.hidden_history
                if any(a in entry.related_actor_ids for a in actor_ids)
            ],
            "currentEvents": _tail(self.current_events, 10),
            "currentRumors": _tail(self.current_rumors, 10),
            "takenActorIds": actor_ids,
            "takenLocationIds": [item.id for item in self.locations],
            "existingAreas": self.areas,
            "recentNarration": self.get_recent_narration(),
            "globalFlags": dict(self.global_flags),
        }

    # -- mutation -----------------------------------------------------------

    def apply_changes(self, event: Dict[str, Any]) -> None:
        narration = ""
        narration_change: Optional[str] = None

        for key, value in event.items():
            if key in ("commandType", "actionScale"):
                continue
            if key == "narration":
                narration = value or ""
            elif key == "narrationChange":
                narration_change = value if isinstance(value, str) else None
            elif key == "stateChanges":
                states = value if isinstance(value, list) else []
                self.apply_states([s for s in states if isinstance(s, dict)])
            else:
                logger.warning(
                    "Unknown entry while applying changes -> %s" % key
                )

        if narration_change is not None:
            if narration_change == "add" and narration:
                merged = "%s %s" % (self._current_narration or "", narration)
                self._current_narration = merged.strip()
            elif narration_change == "replace" and narration:
                self._current_narration = narration.strip()
        elif narration:
            self._current_narration = narration.strip()

    def apply_states(self, states: List[Dict[str, Any]]) -> None:
        for state in states:
            if state.get("type") != "addLocation":
                continue
            payload = state.get("location")
            if isinstance(payload, dict):
                location = Location.from_json(payload)
                if location.id and not self.location_exists(location.id):
                    self.locations.append(location)

        for state in states:
            if state.get("type") != "addActor":
                continue
            payload = state.get("actor")
            if isinstance(payload, dict):
                actor = Actor.from_json(payload)
                if actor.id and not self.actor_exists(actor.id):
                    self.actors.append(actor)

        for state in states:
            if state.get("type") != "updateActor":
                continue
            payload = state.get("actor")
            if isinstance(payload, dict):
                actor = Actor.from_json(payload)
                existing = self.get_actor(actor.id)
                if actor.id and existing is not None:
                    # Prompts ask for a complete actor; merge anyway so a partial
                    # reply cannot silently wipe location, needs or age.
                    merged = _merge(existing.to_json(), payload)
                    self.actors[self.actors.index(existing)] = Actor.from_json(merged)

        handlers = _STATE_HANDLERS
        for state in states:
            kind = str(state.get("type") or "")
            if kind in PREPROCESSED_STATES:
                continue
            handler: Callable[[World, Dict[str, Any]], None] = handlers.get(
                kind, handlers["_default"]
            )
            try:
                handler(self, state)
            except Exception as error:  # keep applying the rest of the batch
                logger.exception("State '%s' failed" % kind, error)

    # -- persistence --------------------------------------------------------

    def write(self) -> None:
        try:
            path = self.save_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.to_json(), indent=4, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            logger.warning("Could not write save -> %r" % error)

    def validate(self) -> List[str]:
        problems: List[str] = []
        for location in self.locations:
            for connected_id in location.connected_location_ids:
                matches = [l for l in self.locations if l.id == connected_id]
                if not matches:
                    problems.append(
                        "location '%s' links to unknown '%s'"
                        % (location.id, connected_id)
                    )
                elif len(matches) > 1:
                    problems.append("duplicate location id '%s'" % connected_id)
                elif location.id not in matches[0].connected_location_ids:
                    problems.append(
                        "connection '%s' -> '%s' is not bidirectional"
                        % (location.id, connected_id)
                    )
            if location.id in location.connected_location_ids:
                problems.append("location '%s' connects to itself" % location.id)

        for actor in self.actors:
            for target_id in actor.relationships:
                if not self.actor_exists(target_id):
                    problems.append(
                        "actor '%s' has a relationship with unknown '%s'"
                        % (actor.id, target_id)
                    )
            if not self.location_exists(actor.location_id):
                problems.append(
                    "actor '%s' is in unknown location '%s'"
                    % (actor.id, actor.location_id)
                )
            if "age" not in actor.status:
                problems.append("actor '%s' has no 'age' in status" % actor.id)

        if self.player_actor is None:
            problems.append("no player actor found")
        return problems

    # -- serialisation ------------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "currentTime": self.current_time.to_json(),
            "settingSummary": self.setting_summary,
            "locations": [location.to_json() for location in self.locations],
            "actors": [actor.to_json() for actor in self.actors],
            "history": [dict(entry) for entry in self.history],
            "currentEvents": [dict(entry) for entry in self.current_events],
            "currentRumors": [dict(entry) for entry in self.current_rumors],
            "hiddenHistory": [entry.to_json() for entry in self.hidden_history],
            "messageHistory": [entry.to_json() for entry in self.message_history],
            "globalFlags": dict(self.global_flags),
        }

    @classmethod
    def from_json(cls, json: Any) -> "World":
        data = json if isinstance(json, dict) else {}
        world = cls(
            id=_text(data.get("id")),
            name=_text(data.get("name")),
            current_time=Time.from_json(data.get("currentTime")),
            setting_summary=_text(data.get("settingSummary")),
            locations=[
                Location.from_json(item)
                for item in _list(data.get("locations"))
            ],
            actors=[Actor.from_json(item) for item in _list(data.get("actors"))],
            history=_entries(data.get("history")),
            current_events=_entries(data.get("currentEvents")),
            current_rumors=_entries(data.get("currentRumors")),
            hidden_history=[
                HiddenHistoryEntry.from_json(item)
                for item in _list(data.get("hiddenHistory"))
            ],
            message_history=[
                ChatEntry.from_json(item)
                for item in _list(data.get("messageHistory"))
            ],
            global_flags=dict(data.get("globalFlags") or {}),
        )
        return world


# ---------------------------------------------------------------------------
# state change handlers
# ---------------------------------------------------------------------------


def _handler(kind: str) -> Callable[[Callable], Callable]:
    def register(func: Callable) -> Callable:
        _STATE_HANDLERS[kind] = func
        return func

    return register


def _st_unknown(world: "World", state: Dict[str, Any]) -> None:
    logger.warning("Unknown state type -> %s" % state.get("type"))


_STATE_HANDLERS["_default"] = _st_unknown


def _get(state: Dict[str, Any], key: str, default: str = "") -> str:
    value = state.get(key, default)
    return default if value is None else str(value)


def _get_int(state: Dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(state.get(key, default))
    except (TypeError, ValueError):
        return default


@_handler("advanceTime")
def _st_advance_time(world: World, state: Dict[str, Any]) -> None:
    seconds = world.parse_seconds_from_advance_time(state)
    if seconds:
        world.advance_time(seconds)


@_handler("moveActor")
def _st_move_actor(world: World, state: Dict[str, Any]) -> None:
    location_id = _get(state, "locationId")
    if location_id and world.location_exists(location_id):
        world.modify_actor_if_exists(
            _get(state, "actorId"), "locationId", location_id
        )


@_handler("removeLocation")
def _st_remove_location(world: World, state: Dict[str, Any]) -> None:
    location_id = _get(state, "locationId")
    world.locations[:] = [l for l in world.locations if l.id != location_id]


@_handler("removeActor")
def _st_remove_actor(world: World, state: Dict[str, Any]) -> None:
    actor_id = _get(state, "actorId")
    world.actors[:] = [a for a in world.actors if a.id != actor_id]


@_handler("setActorDeathTime")
def _st_set_actor_death_time(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    if actor is None:
        return
    death_time = Time.from_json(state.get("deathTime"))
    actor.death_time = death_time
    actor.set_status("currentActivity", "dead")


@_handler("addConnection")
def _st_add_connection(world: World, state: Dict[str, Any]) -> None:
    source = world.get_location(_get(state, "fromLocationId"))
    target = world.get_location(_get(state, "toLocationId"))
    if source is None or target is None:
        return
    source.add_connection(target.id)
    if state.get("bidirectional"):
        target.add_connection(source.id)


@_handler("removeConnection")
def _st_remove_connection(world: World, state: Dict[str, Any]) -> None:
    source = world.get_location(_get(state, "fromLocationId"))
    target = world.get_location(_get(state, "toLocationId"))
    if source is None or target is None:
        return
    source.remove_connection(target.id)
    if state.get("bidirectional"):
        target.remove_connection(source.id)


@_handler("setActorStatus")
def _st_set_actor_status(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    key = _get(state, "key")
    if actor is not None and key:
        actor.set_status(key, state.get("value", ""))


@_handler("setActorPosition")
def _st_set_actor_position(world: World, state: Dict[str, Any]) -> None:
    text = _get(state, "text")
    if text:
        world.modify_actor_if_exists(_get(state, "actorId"), "position", text)


@_handler("removeActorStatus")
def _st_remove_actor_status(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    key = _get(state, "key")
    if actor is not None and key:
        actor.remove_status(key)


@_handler("setRelationship")
def _st_set_relationship(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    target_id = _get(state, "targetActorId")
    if actor is not None and world.actor_exists(target_id):
        actor.set_relationship(target_id, _get_int(state, "value"))


@_handler("changeRelationship")
def _st_change_relationship(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    target_id = _get(state, "targetActorId")
    if actor is not None and world.actor_exists(target_id) and "delta" in state:
        actor.change_relationship(target_id, _get_int(state, "delta"))


@_handler("setLocationStatus")
def _st_set_location_status(world: World, state: Dict[str, Any]) -> None:
    status = _get(state, "status")
    if status:
        world.modify_location_if_exists(
            _get(state, "locationId"), "status", status
        )


@_handler("setLocationFlag")
def _st_set_location_flag(world: World, state: Dict[str, Any]) -> None:
    location = world.get_location(_get(state, "locationId"))
    key = _get(state, "key")
    if location is not None and key:
        location.set_flag(key, state.get("value", ""))


@_handler("removeLocationFlag")
def _st_remove_location_flag(world: World, state: Dict[str, Any]) -> None:
    location = world.get_location(_get(state, "locationId"))
    if location is not None:
        location.remove_flag(_get(state, "key"))


@_handler("addLocationEnvironmentItem")
def _st_add_environment_item(world: World, state: Dict[str, Any]) -> None:
    location = world.get_location(_get(state, "locationId"))
    entry_id = _get(state, "id")
    item = _get(state, "item")
    if location is not None and entry_id and item:
        location.set_environment_item(entry_id, item)


@_handler("removeLocationEnvironmentItem")
def _st_remove_environment_item(world: World, state: Dict[str, Any]) -> None:
    location = world.get_location(_get(state, "locationId"))
    entry_id = _get(state, "id")
    if location is not None and entry_id:
        location.remove_environment_item(entry_id)


@_handler("setActorFlag")
def _st_set_actor_flag(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    key = _get(state, "key")
    if actor is not None and key:
        actor.set_flag(key, state.get("value", ""))


@_handler("removeActorFlag")
def _st_remove_actor_flag(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    if actor is not None:
        actor.remove_flag(_get(state, "key"))


@_handler("setGlobalFlag")
def _st_set_global_flag(world: World, state: Dict[str, Any]) -> None:
    key = _get(state, "key")
    if key:
        world.set_global_flag(key, state.get("value", ""))


@_handler("removeGlobalFlag")
def _st_remove_global_flag(world: World, state: Dict[str, Any]) -> None:
    world.remove_global_flag(_get(state, "key"))


@_handler("setNeed")
def _st_set_need(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    need = _get(state, "need")
    if actor is not None and need:
        actor.needs = actor.needs.change(need, _get_int(state, "value"))


@_handler("changeNeed")
def _st_change_need(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    need = _get(state, "need")
    if actor is not None and need:
        actor.needs = actor.needs.change(need, _get_int(state, "delta"), delta=True)


@_handler("addMemory")
def _st_add_memory(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    entry_id = _get(state, "id")
    content = _get(state, "content")
    if actor is not None and entry_id and content:
        actor.add_memory(entry_id, content, cfg_int("actorMemorySize"))


@_handler("removeMemory")
def _st_remove_memory(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    if actor is not None:
        actor.remove_memory(_get(state, "id"))


@_handler("addKnowledge")
def _st_add_knowledge(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    entry_id = _get(state, "id")
    content = _get(state, "content")
    if actor is not None and entry_id and content:
        actor.add_knowledge(entry_id, content, cfg_int("actorKnowledgeSize"))


@_handler("removeKnowledge")
def _st_remove_knowledge(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    if actor is not None:
        actor.remove_knowledge(_get(state, "id"))


@_handler("addHistory")
def _st_add_history(world: World, state: Dict[str, Any]) -> None:
    world.add_history_entry(_get(state, "id"), _get(state, "content"))


@_handler("removeHistory")
def _st_remove_history(world: World, state: Dict[str, Any]) -> None:
    world.remove_history_entry(_get(state, "id"))


@_handler("addHiddenHistory")
def _st_add_hidden_history(world: World, state: Dict[str, Any]) -> None:
    entry = HiddenHistoryEntry.from_json(state.get("entry"))
    if entry.id:
        world.add_hidden_history(entry)


@_handler("updateHiddenHistory")
def _st_update_hidden_history(world: World, state: Dict[str, Any]) -> None:
    entry = HiddenHistoryEntry.from_json(state.get("entry"))
    if entry.id:
        world.update_hidden_history(entry)


@_handler("removeHiddenHistory")
def _st_remove_hidden_history(world: World, state: Dict[str, Any]) -> None:
    world.remove_hidden_history(_get(state, "id"))


@_handler("addCurrentEvent")
def _st_add_current_event(world: World, state: Dict[str, Any]) -> None:
    world.add_event_entry(_get(state, "id"), _get(state, "content"))


@_handler("removeCurrentEvent")
def _st_remove_current_event(world: World, state: Dict[str, Any]) -> None:
    world.remove_event_entry(_get(state, "id"))


@_handler("addRumor")
def _st_add_rumor(world: World, state: Dict[str, Any]) -> None:
    world.add_rumor_entry(_get(state, "id"), _get(state, "content"))


@_handler("removeRumor")
def _st_remove_rumor(world: World, state: Dict[str, Any]) -> None:
    world.remove_rumor_entry(_get(state, "id"))


@_handler("addInventoryItem")
def _st_add_inventory_item(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    entry_id = _get(state, "id")
    item = _get(state, "item")
    if actor is not None and entry_id and item:
        actor.add_inventory_item(entry_id, item)


@_handler("removeInventoryItem")
def _st_remove_inventory_item(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    if actor is not None:
        actor.remove_inventory_item(_get(state, "id"))


@_handler("setInventory")
def _st_set_inventory(world: World, state: Dict[str, Any]) -> None:
    actor = world.get_actor(_get(state, "actorId"))
    raw = state.get("inventory")
    if actor is not None and isinstance(raw, list):
        actor.inventory = [
            {"id": _text(item.get("id")), "item": _text(item.get("item"))}
            for item in raw
            if isinstance(item, dict)
        ]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _tail(entries: List[Dict[str, str]], count: int) -> List[Dict[str, str]]:
    return [dict(entry) for entry in entries[-count:]]


def _merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Recursive dict merge: values from ``patch`` win, missing keys are kept."""
    result = dict(base)
    for key, value in patch.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _merge(current, value)
        elif value is not None or key not in result:
            result[key] = value
    return result


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _entries(value: Any) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for item in _list(value):
        if isinstance(item, dict):
            result.append(
                {"id": _text(item.get("id")), "content": _text(item.get("content"))}
            )
    return result


def _text(value: Any) -> str:
    return "" if value is None else str(value)