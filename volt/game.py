"""The game session: one process, one loop, no sockets.

The player types free text to act; ``/commands`` drive the console itself.
Generation runs on a worker thread so the loop keeps reading input, which is
what makes ``/cancel`` work and lets background local events appear while the
player is typing.
"""

from __future__ import annotations

import random
import threading
from collections import deque
from typing import Any, Deque, List, Optional, Tuple

from .config import Config
from .console import console
from .engine import CancelToken, Engine
from .locales import describe_generation_error, translator as t
from .logger import logger
from .models import Needs, Role, World
from .models.needs import STANDARD_NEEDS

POLL_INTERVAL = 0.25

COMMANDS: Tuple[Tuple[str, str], ...] = (
    ("help", "cmd.help"),
    ("look", "cmd.look"),
    ("state", "cmd.state"),
    ("who", "cmd.who"),
    ("inventory", "cmd.inventory"),
    ("wait", "cmd.wait"),
    ("cancel", "cmd.cancel"),
    ("revert", "cmd.revert"),
    ("save", "cmd.save"),
    ("reload", "cmd.reload"),
    ("log", "cmd.log"),
    ("exit", "cmd.exit"),
)

ALIASES = {
    "?": "help",
    "h": "help",
    "l": "look",
    "i": "inventory",
    "w": "wait",
    "q": "exit",
    "quit": "exit",
    "s": "save",
    "r": "reload",
}


class GameSession:
    def __init__(self, world: World, config: Config, engine: Engine) -> None:
        self.world = world
        self.config = config
        self.engine = engine
        self._last_state = world.copy()

        self._lock = threading.RLock()
        self._job: Optional[str] = None
        self._token = CancelToken()
        self._queue: Deque[str] = deque()
        self._pending_local_seconds: Optional[int] = None
        self._pending_world_event = False
        self._timer_stop = threading.Event()
        self._timer: Optional[threading.Thread] = None
        self._exited = False

    # -- public API ---------------------------------------------------------

    def run(self) -> None:
        self._start_timer()
        self._show_intro()
        console.hint(t.t("game.prompt") + " " + t.t("game.help") + ": /help")
        console.blank()
        try:
            while not self._exited:
                self._pump()
                try:
                    line = console.ask(self._input_prompt(), timeout=POLL_INTERVAL)
                except EOFError:
                    break
                if line is not None:
                    self._handle(line)
        except KeyboardInterrupt:
            console.blank()
        finally:
            self._exited = True
            self._timer_stop.set()
            self._token.cancel()
            console.flush_narration(5.0)
            self.world.write()
            if self._timer is not None:
                self._timer.join(timeout=2.0)

    # -- input --------------------------------------------------------------

    def _input_prompt(self) -> str:
        marker = ""
        if self._job_name():
            marker = console.dim(" [%s]" % t.t("game.promptBusy"))
        queued = len(self._queue)
        if queued:
            marker += console.dim(" " + t.format("game.promptQueued", count=queued))
        return "%s%s> " % (console.dim(self.world.current_time.short_time), marker)

    def _handle(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        if text.startswith("/") or text.startswith("\\"):
            self._run_command(text[1:].strip())
            return
        if text == self.config.get_text("exitPhrase"):
            self._leave()
            return
        if self._busy():
            self._queue.append(text)
            console.info(t.format("game.promptQueued", count=len(self._queue)))
            return
        self._start_job("prompt", text)

    def _run_command(self, name: str) -> None:
        name = ALIASES.get(name, name).lower()
        if name == "help":
            self._show_help()
        elif name == "look":
            self._show_place()
        elif name == "state":
            self._show_state()
        elif name == "who":
            self._show_nearby()
        elif name == "inventory":
            self._show_inventory()
        elif name == "wait":
            self._show_wait()
        elif name == "cancel":
            self._cancel()
        elif name == "revert":
            self._revert()
        elif name == "save":
            self._save()
        elif name == "reload":
            self._reload()
        elif name == "log":
            self._show_log()
        elif name == "exit":
            self._leave()
        else:
            console.warn(t.format("game.unknownCommand", name=name))

    # -- commands -----------------------------------------------------------

    def _show_help(self) -> None:
        console.rule(t.t("game.help"))
        for name, label in COMMANDS:
            console.kv("/" + name, t.t(label))
        console.blank()

    def _show_place(self) -> None:
        player = self.world.player_actor
        location = self.world.get_location(player.location_id) if player else None
        if location is None:
            console.warn(t.t("state.none"))
            return
        console.rule(location.name or location.id)
        if location.description:
            console.line(location.description)
        if location.status:
            console.kv(t.t("state.status"), location.status)
        nearby = self._nearby_actors()
        if nearby:
            console.kv(t.t("state.nearby"), ", ".join(nearby))
        connected = self.world.get_connected_locations(location.id)
        if connected:
            console.kv(
                t.t("state.connected"),
                ", ".join(item.name or item.id for item in connected),
            )
        if location.environment_and_items:
            console.blank()
            console.kv(t.t("state.position"), "")
            for item_id, item in location.environment_and_items.items():
                console.line("  %s %s" % (console.dim("-"), item or item_id))
        console.blank()

    def _show_state(self) -> None:
        world = self.world
        console.rule(t.t("state.world"))
        console.kv(t.t("state.time"), world.current_time.short_time)
        console.kv(
            t.t("state.world"),
            "%s (%s)" % (world.name or t.t("state.none"), world.id),
        )
        console.kv(
            t.t("state.actors"),
            "%d" % len(world.actors),
        )
        console.kv(
            t.t("state.locations"),
            "%d" % len(world.locations),
        )

        player = world.player_actor
        if player is None:
            console.warn(t.t("world.problems"))
            return

        location = world.get_location(player.location_id)
        console.kv(t.t("state.player"), _actor_label(player))
        if location is not None:
            console.kv(t.t("state.location"), "%s (%s)" % (location.name, location.id))
        if player.position:
            console.kv(t.t("state.position"), player.position)
        status = ", ".join(
            "%s: %s" % (_prettify_key(key), value)
            for key, value in player.status.items()
            if key not in ("age", "role")
        )
        if status:
            console.kv(t.t("state.status"), status)
        if "age" in player.status:
            console.kv(t.t("state.status"), "age: %s" % player.status["age"])
        console.blank()
        self._show_needs(player.needs)

        for title, entries in (
            (t.t("state.events"), world.current_events),
            (t.t("state.rumors"), world.current_rumors),
            (t.t("state.history"), world.history[-5:]),
        ):
            if not entries:
                continue
            console.kv(title, "")
            for entry in entries[-5:]:
                console.line("  %s %s" % (console.dim("-"), entry.get("content", "")))
        if world.global_flags:
            console.kv(t.t("state.flags"), ", ".join(sorted(world.global_flags)))
        console.blank()

    def _show_needs(self, needs: Needs) -> None:
        console.kv(t.t("state.needs"), "")
        for name, value in sorted(needs.as_dict().items(), key=lambda i: -i[1]):
            if value <= 0:
                continue
            filled = min(20, int(round(value / 5.0)))
            bar = "#" * filled + "-" * (20 - filled)
            label = t.t("needs." + name) if name in STANDARD_NEEDS else name
            console.line(
                "  %s %s %s"
                % (label.ljust(14), console.dim(bar), "%3d" % value)
            )
        console.blank()

    def _nearby_actors(self) -> List[str]:
        player = self.world.player_actor
        if player is None:
            return []
        location = self.world.get_location(player.location_id)
        if location is None:
            return []
        return [
            _actor_label(actor)
            for actor in self.world.get_actors_in_area(location.area, player.id)
        ]

    def _show_nearby(self) -> None:
        nearby = self._nearby_actors()
        if not nearby:
            console.hint(t.t("state.none"))
            return
        console.rule(t.t("state.nearby"))
        console.bullets(nearby)
        console.blank()

    def _show_inventory(self) -> None:
        player = self.world.player_actor
        if player is None or not player.inventory:
            console.hint(t.t("state.none"))
            return
        console.rule(t.t("cmd.inventory"))
        for item in player.inventory:
            console.line("  %s %s" % (console.dim("-"), item.get("item") or item.get("id")))
        console.blank()

    def _show_wait(self) -> None:
        minutes = console.ask_int("%s " % t.t("cmd.wait"), minimum=1, maximum=600)
        if minutes is None:
            return
        seconds = minutes * 60
        if self._busy():
            self._pending_local_seconds = seconds
            console.info(
                t.format(
                    "game.waitQueued",
                    time="%d %s" % (minutes, t.t("common.minutes")),
                )
            )
            return
        self._start_job("local_event", seconds)

    def _cancel(self) -> None:
        job = self._job_name()
        if not job:
            console.hint(t.t("game.cancelNothing"))
            return
        if job != "prompt":
            console.warn(t.t("game.cannotCancel"))
            return
        if self._token.cancelled:
            console.info(t.t("game.cancelPending"))
            return
        self._token.cancel()
        console.info(t.t("game.cancelRequested"))

    def _revert(self) -> None:
        if self._busy():
            console.warn(t.t("game.revertBusy"))
            return
        self.world = self._last_state.copy()
        self.world.write()
        console.ok(t.t("game.reverted"))
        self._print_narration_history()

    def _save(self) -> None:
        self.world.write()
        console.ok(t.t("game.saved"))

    def _reload(self) -> None:
        messages = self.world.get_recent_narration(1)
        if not messages:
            console.hint(t.t("game.revertNothing"))
            return
        self._narrate(messages[0])

    def _show_log(self) -> None:
        count = console.ask_int("%s " % t.t("cmd.log"), minimum=1, maximum=200)
        if count is None:
            return
        tail = logger.tail(count)
        console.rule(t.t("cmd.log"))
        if tail:
            for line in tail.splitlines():
                console.line(console.dim(line))
        else:
            console.hint(t.t("state.none"))
        console.blank()

    def _leave(self) -> None:
        if self._job_name() == "prompt":
            console.warn(t.t("game.exitWhileBusy"))
        self.world.write()
        console.ok(t.t("game.saved"))
        console.info(t.t("game.goodbye"))
        self._exited = True

    # -- scheduling ---------------------------------------------------------

    def _busy(self) -> bool:
        with self._lock:
            return self._job is not None

    def _job_name(self) -> Optional[str]:
        with self._lock:
            return self._job

    def _start_job(self, kind: str, payload: Any = None) -> None:
        with self._lock:
            if self._job is not None:
                return
            self._job = kind
            self._token.reset()
        thread = threading.Thread(
            target=self._run_job, args=(kind, payload), name="volt-job", daemon=True
        )
        thread.start()

    def _pump(self) -> None:
        """Start whatever is waiting, in priority order, when idle."""
        if self._busy() or self._exited:
            return
        if self._queue:
            self._start_job("prompt", self._queue.popleft())
            return
        if self._pending_local_seconds is not None:
            seconds = self._pending_local_seconds
            self._pending_local_seconds = None
            self._start_job("local_event", seconds)
            return
        if self._pending_world_event:
            self._pending_world_event = False
            self._start_job("world_event")

    # -- jobs ---------------------------------------------------------------

    def _run_job(self, kind: str, payload: Any) -> None:
        rolled_over = False
        try:
            if kind == "prompt":
                rolled_over = self._job_prompt(payload)
            elif kind == "local_event":
                rolled_over = self._job_local_event(int(payload))
            elif kind == "world_event":
                self._job_world_event()
        except Exception as error:
            logger.exception("Job '%s' crashed" % kind, error)
            console.error("%s: %r" % (t.t("game.failed"), error))
        finally:
            with self._lock:
                self._job = None
            if self._exited:
                return
            try:
                rolled_over = self.world.new_day or rolled_over
            except Exception:
                rolled_over = False
            if rolled_over:
                console.info(t.t("game.newDay"))
                self._pending_world_event = True
            # Continue queued work immediately instead of waiting for the player
            # to press Enter again.
            self._pump()

    def _job_prompt(self, command: str) -> bool:
        console.info(t.t("game.promptBusy") + "...")
        self._last_state = self.world.copy()
        result = self.engine.generate_player_action_event(
            command, self.world, self._token
        )
        if result.canceled:
            console.info(t.t("game.cancelled"))
            return False
        if not result.ok or not isinstance(result.data, dict):
            console.error(describe_generation_error(result.error))
            return False

        payload = result.data
        self.world.apply_changes(payload.get("playerEvent") or {})
        local = payload.get("localEvent")
        if isinstance(local, dict):
            self.world.apply_changes(local)

        narration = self.world.get_current_narration()
        self.world.add_message_to_history(Role.USER, command)
        if narration:
            self.world.add_message_to_history(
                Role.ASSISTANT,
                "%s: %s" % (self.world.current_time.short_time, narration),
            )
        self.world.write()
        self._emit(narration)
        return False

    def _job_local_event(self, seconds: int) -> bool:
        self.world.advance_time(seconds)
        console.info(
            t.format(
                "game.localEvent",
                time="%d %s" % (seconds, t.t("common.seconds")),
            )
        )

        attempts = max(1, self.config.get_int("regenerateAttempts"))
        for attempt in range(attempts):
            result = self.engine.generate_local_event(
                seconds, self.world, self._token
            )
            if result.canceled:
                console.info(t.t("game.cancelled"))
                self._restore_last_state()
                return False
            if result.ok and isinstance(result.data, dict):
                self.world.apply_changes(result.data)
                narration = self.world.get_current_narration()
                if narration:
                    self.world.add_message_to_history(
                        Role.ASSISTANT,
                        "%s: %s"
                        % (self.world.current_time.short_time, narration),
                    )
                self._last_state = self.world.copy()
                self.world.write()
                self._emit(narration)
                return False
            if result.error:
                console.error(describe_generation_error(result.error))
            if attempt + 1 < attempts:
                console.hint(
                    "%s (%d/%d)" % (t.t("game.failed"), attempt + 1, attempts)
                )

        self._restore_last_state()
        return False

    def _job_world_event(self) -> bool:
        console.info(t.t("game.worldEvent"))
        attempts = max(1, self.config.get_int("regenerateAttempts"))
        for attempt in range(attempts):
            result = self.engine.generate_world_event(self.world, self._token)
            if result.canceled:
                console.info(t.t("game.cancelled"))
                return False
            if result.ok and isinstance(result.data, dict):
                self.world.apply_changes(result.data)
                narration = self.world.get_current_narration()
                if narration:
                    self.world.add_message_to_history(
                        Role.ASSISTANT,
                        "%s: %s"
                        % (self.world.current_time.short_time, narration),
                    )
                self._last_state = self.world.copy()
                self.world.write()
                self._emit(narration)
                return False
            if result.error:
                console.error(describe_generation_error(result.error))
            if attempt + 1 < attempts:
                console.hint(
                    "%s (%d/%d)" % (t.t("game.failed"), attempt + 1, attempts)
                )
        return False

    def _restore_last_state(self) -> None:
        """Undo time that was advanced for a generation that did not happen."""
        self.world = self._last_state.copy()

    def _emit(self, narration: str) -> None:
        if not narration:
            console.hint(t.t("game.quiet"))
            return
        self._narrate(narration)

    def _narrate(self, text: str) -> None:
        console.narrate(text, speed=self.config.text_speed)

    def _print_narration_history(self) -> None:
        for message in self.world.get_recent_narration(3):
            self._narrate(message)

    # -- intro / background -------------------------------------------------

    def _show_intro(self) -> None:
        console.clear()
        console.rule(self.world.name or self.world.id)
        if self.world.setting_summary:
            console.line(self.world.setting_summary)
            console.blank()
        player = self.world.player_actor
        if player is not None:
            location = self.world.get_location(player.location_id)
            if location is not None:
                console.kv(t.t("state.time"), self.world.current_time.short_time)
                console.kv(
                    t.t("state.location"),
                    "%s — %s" % (location.name, location.description),
                )
        console.blank()

    def _start_timer(self) -> None:
        if self._timer is not None:
            return
        self._timer = threading.Thread(
            target=self._timer_loop, name="volt-timer", daemon=True
        )
        self._timer.start()

    def _timer_loop(self) -> None:
        passed = 0
        while not self._timer_stop.wait(1.0):
            if self._busy() or self._exited:
                continue
            if not self.config.get_bool("generateLocalEvents"):
                continue
            passed += 1
            interval = max(30, self.config.get_int("localEventInterval"))
            if passed < interval:
                continue
            chance = 30 + ((passed - interval) // max(1, interval // 2))
            if random.randint(1, 100) <= chance:
                with self._lock:
                    if self._pending_local_seconds is None:
                        self._pending_local_seconds = passed
                passed = 0


def _prettify_key(key: str) -> str:
    """``currentActivity`` -> ``current activity``."""
    text = "".join(" " + ch.lower() if ch.isupper() else ch for ch in key)
    return text.strip()


def _actor_label(actor) -> str:
    label = "%s (%s)" % (actor.name or actor.id, actor.id)
    if actor.is_dead:
        label += " — " + t.t("state.dead")
    elif actor.status.get("isBirthday"):
        label += " — " + t.t("state.birthday")
    return label