"""Append-only log file with size based rotation."""

from __future__ import annotations

import threading
from datetime import datetime
from enum import Enum
from typing import Optional

from . import paths


class LogLevel(Enum):
    LOG = "LOG"
    WARNING = "WARNING"
    FATAL = "FATAL"


class Logger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rotation = True
        self._rotation_limit = 1000
        self._path = paths.LOG_PATH
        self.echo_to_stderr = False

    def configure(self, rotation: bool, rotation_limit: int) -> None:
        with self._lock:
            self._rotation = rotation
            self._rotation_limit = max(1, rotation_limit)

    def log(self, message: str, level: LogLevel = LogLevel.LOG) -> None:
        line = "[%s] (%s) %s\n" % (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            level.value,
            message.strip(),
        )
        with self._lock:
            try:
                self._rotate()
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except OSError:
                pass
            if self.echo_to_stderr and level is not LogLevel.LOG:
                import sys

                print(message.strip(), file=sys.stderr)

    def warning(self, message: str) -> None:
        self.log(message, LogLevel.WARNING)

    def exception(self, message: str, error: BaseException) -> None:
        self.log("%s -> %r" % (message, error), LogLevel.WARNING)

    def tail(self, count: int = 20) -> Optional[str]:
        """Last ``count`` lines of the log, for the in-game ``/log`` command."""
        try:
            content = self._path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        lines = [line for line in content.splitlines() if line.strip()]
        return "\n".join(lines[-count:]) or None

    def _rotate(self) -> None:
        if not self._rotation:
            return
        try:
            if self._path.stat().st_size == 0:
                return
            with self._path.open("r", encoding="utf-8", errors="replace") as handle:
                lines = sum(1 for _ in handle)
        except OSError:
            return
        if lines > self._rotation_limit:
            try:
                self._path.write_text("", encoding="utf-8")
            except OSError:
                pass


logger = Logger()