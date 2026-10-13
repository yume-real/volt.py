#!/usr/bin/env python3
"""Volt.py - a console text world simulation.

A fork of https://github.com/ThetaInterface/volt, rewritten in Python: one
process, one terminal, no websocket server and no GUI dialog binaries.

Usage::

    python Volt.py               # menu
    python Volt.py --saves       # list saves
    python Volt.py --no-color    # disable ANSI colours
    python Volt.py --lang en     # override the interface language
    python Volt.py --debug       # dump raw LLM replies into ./debug

Everything runs in a single process and reads all input from the terminal.
"""

from __future__ import annotations

import argparse
import os
import sys

from volt import __version__

NAME = "Volt.py"
DEBUG_ENV = "VOLT_PY_DEBUG"


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(
        prog=NAME.lower(),
        description="%s - a console text world simulation" % NAME,
    )
    parser.add_argument("--no-color", action="store_true", help="disable colours")
    parser.add_argument("--lang", help="interface language, e.g. ru / en")
    parser.add_argument("--saves", action="store_true", help="list save files")
    parser.add_argument(
        "--debug", action="store_true", help="dump raw LLM replies into ./debug"
    )
    parser.add_argument(
        "--version", action="version", version="%s %s" % (NAME, __version__)
    )
    args = parser.parse_args(argv)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"
    if args.debug:
        os.environ[DEBUG_ENV] = "1"

    from volt import context, paths, saves
    from volt.config import Config
    from volt.console import console
    from volt.locales import translator
    from volt.logger import logger

    paths.ensure_dirs()

    if args.saves:
        items = saves.list_saves()
        if not items:
            print("no saves in %s" % paths.SAVES_DIR)
            return 0
        for item in items:
            print(
                "%s  %-30s %s"
                % (item.path.name, item.title, item.modified.strftime("%Y-%m-%d %H:%M"))
            )
        return 0

    config = Config.load()
    if args.lang:
        config.values["language"] = args.lang
        config.save()

    context.set_config(config)
    translator.load(config.get_text("language"))
    console.bind_locale(
        lambda key, fallback: translator.t(key, fallback), translator.error
    )
    logger.configure(
        config.get_bool("logRotation"), config.get_int("logRotationLimit")
    )

    from volt.ui import App

    try:
        return App().run()
    except KeyboardInterrupt:
        console.blank()
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))