"""Menus: main, play, saves, settings and the new-world wizard."""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import platform

from . import __author__, __upstream__, __version__, locales, paths, saves
from .config import FIELDS, MODEL_LISTING_PROVIDERS, Config, Field
from .console import console
from .context import set_config
from .engine import CancelToken, Engine, GenerationResult
from .game import GameSession
from .locales import Locale, describe_generation_error, translator as t
from .logger import logger
from .models import World


MAIN_MENU = (
    ("play", "menu.play"),
    ("saves", "menu.saves"),
    ("settings", "menu.settings"),
    ("about", "menu.about"),
    ("exit", "menu.exit"),
)


class App:
    def __init__(self) -> None:
        self.config = Config.load()
        set_config(self.config)
        self.apply_locale()
        self.engine = Engine(self.config)

    # -- lifecycle ----------------------------------------------------------

    def apply_locale(self) -> None:
        t.load(self.config.get_text("language"))
        console.bind_locale(lambda key, fallback: t.t(key, fallback), t.error)

    def refresh(self) -> None:
        self.config = Config.load()
        set_config(self.config)
        self.apply_locale()
        logger.configure(
            self.config.get_bool("logRotation"),
            self.config.get_int("logRotationLimit"),
        )
        self.engine = Engine(self.config)

    def run(self) -> int:
        paths.ensure_dirs()
        logger.configure(
            self.config.get_bool("logRotation"),
            self.config.get_int("logRotationLimit"),
        )
        console.clear()
        console.line(
            console.bold("%s %s" % (t.t("app.title"), __version__))
            + " "
            + console.dim(t.t("app.tagline"))
        )
        console.blank()
        while True:
            try:
                action = self._main_menu()
                if action == "play":
                    self.play()
                elif action == "saves":
                    self.saves_menu()
                elif action == "settings":
                    self.settings_menu()
                elif action == "about":
                    self.about()
                elif action == "exit":
                    console.info(t.t("menu.exit"))
                    return 0
            except KeyboardInterrupt:
                console.blank()
                return 0
            except EOFError:
                console.blank()
                return 0

    # -- menus --------------------------------------------------------------

    def _main_menu(self) -> str:
        """Render the menu and return the id of the chosen action."""
        console.clear()
        console.rule(t.t("menu.title"))
        console.numbered([t.t(label) for _action, label in MAIN_MENU])
        console.blank()
        choice = console.ask_int(
            "%s: " % t.t("menu.prompt"), minimum=1, maximum=len(MAIN_MENU)
        )
        if choice is None:
            raise EOFError
        return MAIN_MENU[choice - 1][0]

    def play(self) -> None:
        world = self._choose_save()
        if world is None:
            return
        session = GameSession(world, self.config, self.engine)
        session.run()
        self.refresh()

    def _choose_save(self) -> Optional[World]:
        console.clear()
        console.rule(t.t("menu.play"))
        available = saves.list_saves()
        entries = [t.t("world.title")]
        for item in available:
            entries.append("%s %s" % (item.title, console.dim(_when(item))))
        if not available:
            console.hint(t.t("saves.empty"))
        console.numbered(entries)
        console.blank()
        choice = console.ask_int(
            "%s: " % t.t("menu.prompt"), minimum=1, maximum=len(entries)
        )
        if choice is None or choice == 1:
            return self.create_world()
        info = available[choice - 2]
        world = saves.load_world(info.path)
        if world is None:
            console.error(t.t("saves.loadFailed"))
            return None
        console.ok(t.format("world.loaded", name=world.name or world.id))
        self._report_problems(world)
        return world

    def _report_problems(self, world: World) -> None:
        problems = world.validate()
        if not problems:
            console.hint(t.t("world.noProblems"))
            return
        console.warn(t.t("world.problems"))
        console.bullets(problems[:10])
        if len(problems) > 10:
            console.hint(t.t("common.more"))

    def create_world(self) -> Optional[World]:
        console.clear()
        console.rule(t.t("world.title"))
        summary = console.ask_multiline(
            t.t("world.summaryPrompt") + "\n" + console.dim(t.t("world.summaryHelp"))
        )
        if not summary.strip():
            console.warn(t.t("world.summaryEmpty"))
            return None

        problem = self.engine.check_provider()
        if problem:
            console.error(describe_generation_error(problem))
            return None

        token = CancelToken()
        try:
            result = console.spinner_run(
                lambda: self.engine.generate_world(summary, token),
                t.t("world.generating"),
            )
        except KeyboardInterrupt:
            console.blank()
            console.warn(t.t("game.cancelled"))
            return None

        if not isinstance(result, GenerationResult):
            console.error(t.t("world.failed"))
            return None
        if result.canceled:
            console.warn(t.t("game.cancelled"))
            return None
        if not result.ok or not isinstance(result.data, World):
            console.error(describe_generation_error(result.error))
            return None

        world: World = result.data
        world.save_path = paths.SAVES_DIR / saves.file_name_for(world.id)
        world.write()
        console.ok(t.format("world.generated", name=world.name or world.id))
        console.hint(t.format("world.savedAs", path=world.save_path))
        self._report_problems(world)
        return world

    # -- saves --------------------------------------------------------------

    def saves_menu(self) -> None:
        while True:
            console.clear()
            console.rule(t.t("saves.title"))
            available = saves.list_saves()
            if not available:
                console.hint(t.t("saves.empty"))
                console.blank()
                console.ask("")
                return
            for index, item in enumerate(available, 1):
                console.line(
                    "  %s %s %s"
                    % (
                        console.magenta("%2d)" % index),
                        item.title.ljust(38),
                        console.dim("%s  %s" % (item.world_id, _when(item))),
                    )
                )
            console.line(
                "  %s %s" % (console.magenta(" 0)"), t.t("common.back"))
            )
            console.blank()
            choice = console.ask_int(
                "%s: " % t.t("saves.title"), minimum=0, maximum=len(available)
            )
            if not choice:
                return
            self._edit_save(available[choice - 1])

    def _edit_save(self, info: saves.SaveInfo) -> None:
        world = saves.load_world(info.path)
        if world is None:
            console.error(t.t("saves.loadFailed"))
            return

        while True:
            console.clear()
            console.rule("%s: %s" % (t.t("saves.title"), info.title))
            console.kv(t.t("saves.id"), world.id)
            console.kv(t.t("saves.name"), world.name or t.t("state.none"))
            console.kv(t.t("common.path"), str(info.path))
            console.blank()
            entries = [
                t.t("saves.editId"),
                t.t("saves.editName"),
                t.t("saves.save"),
                t.t("saves.duplicated"),
                t.t("saves.delete"),
                t.t("common.back"),
            ]
            console.numbered(entries)
            console.blank()
            choice = console.ask_int(
                "%s: " % t.t("menu.prompt"), minimum=1, maximum=len(entries)
            )
            if choice == 1:
                self._rename(world, info, is_id=True)
            elif choice == 2:
                self._rename(world, info, is_id=False)
            elif choice == 3:
                self._delete(world, info)
                return
            elif choice == 4:
                target = saves.duplicate(world)
                console.ok(t.t("saves.duplicated"))
                console.hint(str(target))
            elif choice == 5:
                self._delete(world, info)
                return
            elif choice == 6:
                return

    def _rename(self, world: World, info: saves.SaveInfo, is_id: bool) -> None:
        label = t.t("saves.editId") if is_id else t.t("saves.editName")
        value = console.ask_text("%s: " % label)
        if not value:
            return
        if is_id:
            if saves.INVALID_ID_CHARS.search(value):
                console.error(t.t("saves.badId"))
                return
            world.id = value
        else:
            world.name = value

        target = paths.SAVES_DIR / saves.file_name_for(world.id)
        if target != info.path:
            saves.delete_save(info.path)
        world.save_path = target
        world.write()
        info.path = target
        info.world_id = world.id
        info.world_name = world.name
        console.ok(t.t("saves.edited"))

    def _delete(self, world: World, info: saves.SaveInfo) -> None:
        if not console.ask_bool("%s " % t.t("saves.deletedAsk"), default=False):
            return
        if saves.delete_save(info.path):
            console.ok(t.t("saves.deleted"))
        else:
            console.error(t.t("saves.loadFailed"))

    # -- settings -----------------------------------------------------------

    def about(self) -> None:
        """Show version, authorship and where the files live."""
        console.clear()
        console.rule("%s %s" % (t.t("app.title"), __version__))
        console.blank()
        console.line(t.t("app.tagline"))
        console.blank()
        console.kv(t.t("about.version"), __version__)
        console.kv(t.t("about.author"), __author__)
        console.kv(t.t("about.license"), t.t("about.licenseValue"))
        console.kv(t.t("about.fork"), __upstream__)
        console.blank()

        url, _key, model = self.config.provider_endpoint()
        console.kv(t.t("about.python"), platform.python_version())
        console.kv(t.t("about.provider"), self.config.provider)
        console.kv(t.t("about.model"), model or t.t("state.none"))
        console.kv(t.t("about.endpoint"), url or t.t("state.none"))
        console.kv(t.t("about.saves"), str(len(saves.list_saves())))
        console.kv(t.t("about.path"), str(paths.PROGRAM_DIR))
        console.kv(t.t("about.locale"), locales.translator.locale.display_name)
        console.blank()
        console.hint(t.t("about.docs"))

    def settings_menu(self) -> None:
        while True:
            console.clear()
            console.rule(t.t("settings.title"))
            for index, spec in enumerate(FIELDS, 1):
                console.line(
                    "  %s %s %s"
                    % (
                        console.magenta("%2d)" % index),
                        _label(spec).ljust(38),
                        _display(self.config, spec),
                    )
                )
            console.line("  %s %s" % (console.magenta(" 0)"), t.t("common.back")))
            console.line("  %s %s" % (console.magenta(" r)"), t.t("settings.resetAsk")))
            console.blank()
            console.hint(t.t("settings.hint"))
            console.blank()
            answer = console.ask("%s: " % t.t("settings.title"))
            if answer is None:
                raise EOFError
            answer = answer.strip().lower()
            if not answer or answer == "0":
                return
            if answer in ("r", "с", "reset"):
                if console.ask_bool("%s " % t.t("settings.resetAsk"), default=False):
                    self.config.reset()
                    self.refresh()
                    console.ok(t.t("settings.resetDone"))
                continue
            try:
                index = int(answer)
            except ValueError:
                console.error(t.t("error.not_a_number"))
                continue
            if not 1 <= index <= len(FIELDS):
                continue
            self._edit_field(FIELDS[index - 1])

    def _edit_field(self, spec: Field) -> None:
        console.clear()
        console.rule(_label(spec))
        console.kv(t.t("settings.current"), _display(self.config, spec))
        if spec.kind == "bool":
            value = console.ask_bool(
                "%s (%s) "
                % (
                    t.t("settings.new"),
                    t.format(
                        "settings.on",
                        yes=t.t("common.yes"),
                        no=t.t("common.no"),
                    ),
                ),
                default=self.config.get_bool(spec.key),
            )
        elif spec.kind == "choice":
            value = self._choose_from(
                list(spec.choices), self.config.get_text(spec.key)
            )
            if value is None:
                return
        elif spec.kind == "language":
            locales = self._available_locales()
            value = self._choose_from(
                locales, self.config.get_text(spec.key), lambda item: item[0],
                lambda item: item[1],
            )
            if value is None:
                return
        elif spec.kind == "secret":
            value = console.ask_text(
                "%s (%s): " % (t.t("settings.new"), t.t("settings.keep"))
            )
            if not value:
                console.hint(t.t("settings.keep"))
                return
        elif spec.kind == "model":
            value = self._edit_model(spec)
            if value is None:
                return
        elif spec.kind == "ratio":
            console.kv(t.t("settings.min"), spec.minimum)
            console.kv(t.t("settings.max"), spec.maximum)
            value = self._ask_float(spec)
            if value is None:
                return
        else:
            console.kv(t.t("settings.min"), spec.minimum)
            console.kv(t.t("settings.max"), spec.maximum)
            value = console.ask_int(
                "%s: " % t.t("settings.new"), minimum=int(spec.minimum or 0)
            )
            if value is None:
                return

        stored = self.config.set(spec.key, value)
        if spec.key == "language":
            self.refresh()
        else:
            self.engine = Engine(self.config)
        shown = "" if spec.kind == "secret" else str(stored)
        console.ok(t.format("settings.saved", name=_label(spec), value=shown))
        console.blank()

    def _edit_model(self, spec: Field) -> Optional[str]:
        """Pick a model from the provider list, or type one by hand."""
        current = self.config.get_text(spec.key)
        console.kv(t.t("settings.current"), current or t.t("settings.secretEmpty"))

        if self.config.provider in MODEL_LISTING_PROVIDERS and self.config.api_key:
            if console.ask_bool("%s " % t.t("settings.modelsFetch"), default=False):
                models = console.spinner_run(
                    self.engine.list_models, t.t("settings.modelsLoading")
                )
                if models:
                    value = self._choose_from(
                        models, current, lambda item: item[0], lambda item: item[1]
                    )
                    if value is not None:
                        return value
                else:
                    console.warn(t.t("settings.modelsFailed"))

        return console.ask_text("%s: " % t.t("settings.new")) or None

    def _ask_float(self, spec: Field) -> Optional[float]:
        while True:
            raw = console.ask("%s: " % t.t("settings.new"))
            if raw is None:
                return None
            raw = raw.strip().replace(",", ".")
            if not raw:
                return None
            try:
                value = float(raw)
            except ValueError:
                console.error(t.t("error.not_a_number"))
                continue
            if spec.minimum is not None and value < spec.minimum:
                console.error("%s %s" % (t.t("error.too_small"), spec.minimum))
                continue
            if spec.maximum is not None and value > spec.maximum:
                console.error("%s %s" % (t.t("error.too_big"), spec.maximum))
                continue
            return value

    def _choose_from(
        self,
        options: List,
        current: str,
        key: Optional[Callable] = None,
        label: Optional[Callable] = None,
    ) -> Optional[str]:
        get_key = key or (lambda item: item)
        get_label = label or (lambda item: str(item))
        entries = []
        for item in options:
            marker = console.green("*") if get_key(item) == current else " "
            entries.append("%s %s" % (marker, get_label(item)))
        console.numbered(entries)
        console.blank()
        choice = console.ask_int(
            "%s: " % t.t("settings.language"), minimum=1, maximum=len(options)
        )
        if choice is None:
            return None
        return get_key(options[choice - 1])

    def _available_locales(self) -> List[Tuple[str, str]]:
        return [(locale.name, locale.display_name) for locale in Locale.available()]


def _label(spec: Field) -> str:
    return t.t(spec.label)


def _display(config: Config, spec: Field) -> str:
    if spec.kind == "secret":
        value = config.get_text(spec.key)
        return console.green(t.t("settings.secretSet")) if value else console.dim(
            t.t("settings.secretEmpty")
        )
    if spec.kind == "bool":
        return t.t("common.yes") if config.get_bool(spec.key) else t.t("common.no")
    value = config.get(spec.key)
    if spec.kind == "choice":
        return str(value)
    if spec.kind == "ratio":
        return "%.2f" % float(value)
    return str(value)


def _when(info: saves.SaveInfo) -> str:
    return info.modified.strftime("%Y-%m-%d %H:%M")