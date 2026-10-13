"""Terminal front-end helpers.

Two things make this console pleasant to use:

* :class:`ConsoleInput` can poll the keyboard with a timeout, so background
  events (local events, generation results) may be printed while the player is
  in the middle of typing a command.
* Every write to the terminal goes through :meth:`Console.raw`, which erases
  and redraws the active input line, so output never garbles what is being
  typed.
"""

from __future__ import annotations

import atexit
import os
import queue
import sys
import threading
import time
from typing import Callable, Iterable, Optional, Sequence

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"

_PUNCTUATION = set(".,;:!?…\u2014-\u2013")


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("VOLT_PY_FORCE_COLOR"):
        return True
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _enable_windows_vt() -> None:
    if os.name != "nt":
        return
    if not getattr(sys.stdout, "isatty", lambda: False)():
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_STD_INPUT_HANDLE = -10
_ENABLE_PROCESSED_INPUT = 0x0001
_ENABLE_LINE_INPUT = 0x0002
_ENABLE_ECHO_INPUT = 0x0004

_saved_console_mode = None


def _windows_console_mode(handle: Optional[int] = None) -> bool:
    """Switch the console to per-keystroke input without its own echo.

    Line input and echo are turned off because characters are read one by one
    and echoed by us (so the active line can be redrawn). The previous mode is
    restored on exit, otherwise the shell would be left without echo.
    """
    global _saved_console_mode
    if os.name != "nt":
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if handle is None:
            handle = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if _saved_console_mode is None:
            _saved_console_mode = mode.value
            atexit.register(_restore_windows_console_mode)
        wanted = (
            mode.value & ~(_ENABLE_LINE_INPUT | _ENABLE_ECHO_INPUT)
        ) | _ENABLE_PROCESSED_INPUT
        return bool(kernel32.SetConsoleMode(handle, wanted))
    except Exception:
        return False


def _restore_windows_console_mode() -> None:
    if os.name != "nt" or _saved_console_mode is None:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(
            kernel32.GetStdHandle(_STD_INPUT_HANDLE), _saved_console_mode
        )
    except Exception:
        pass


class ConsoleInput:
    """Line editor with timeout support."""

    def __init__(self, console: "Console") -> None:
        self._console = console
        self._lock = console.lock
        self._prompt = ""
        self._buffer = ""
        self._active = False
        self._reader_started = False
        self._reader_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._mode = self._detect_mode()

    def _detect_mode(self) -> str:
        if not getattr(sys.stdin, "isatty", lambda: False)():
            return "thread"
        if os.name == "nt":
            try:
                import msvcrt  # noqa: F401

                return "windows"
            except Exception:
                return "thread"
        try:
            import termios  # noqa: F401
            import tty  # noqa: F401

            return "posix"
        except Exception:
            return "thread"

    # -- public API ---------------------------------------------------------

    def prompt(self, text: str) -> None:
        with self._lock:
            self._set_prompt(text)

    def read_line(self, timeout: Optional[float] = None) -> Optional[str]:
        """Return a finished line, or ``None`` if ``timeout`` elapsed first."""
        if not self._active:
            self._begin()
        if self._mode == "thread":
            self._start_reader_thread()
            return self._read_line_thread(timeout)
        if self._mode == "windows":
            return self._read_line_windows(timeout)
        return self._read_line_native(timeout)

    def _begin(self) -> None:
        with self._lock:
            self._buffer = ""
            self._active = True
            self._draw_input_line()

    def _set_prompt(self, text: str) -> None:
        with self._lock:
            self._prompt = text
            if self._active:
                self._draw_input_line()

    def _draw_input_line(self) -> None:
        sys.stdout.write("\r\x1b[2K" + self._prompt + self._buffer)
        sys.stdout.flush()

    def _read_line_thread(self, timeout: Optional[float]) -> Optional[str]:
        try:
            line = self._reader_queue.get(timeout=timeout)
        except queue.Empty:
            return None
        with self._lock:
            self._active = False
            self._console.raw(line + "\n" if line else "\n")
        if line is None:
            raise EOFError
        return line

    def _start_reader_thread(self) -> None:
        if self._reader_started:
            return
        self._reader_started = True

        def worker() -> None:
            while True:
                try:
                    line = sys.stdin.readline()
                except Exception:
                    break
                if line == "":
                    self._reader_queue.put(None)
                    break
                self._reader_queue.put(line.rstrip("\r\n"))

        threading.Thread(target=worker, name="volt-stdin", daemon=True).start()

    def _read_line_native(self, timeout: Optional[float]) -> Optional[str]:
        deadline = None if timeout is None else time.monotonic() + timeout
        import termios
        import tty

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                wait = None
                if deadline is not None:
                    wait = deadline - time.monotonic()
                    if wait <= 0:
                        return None
                char = self._read_char_native(fd, wait)
                if char is None:
                    return None
                line = self._handle_char(char)
                if line is not None:
                    return line
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    def _read_char_native(self, fd: int, timeout: Optional[float]) -> Optional[str]:
        import select

        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        data = os.read(fd, 32)
        if not data:
            raise EOFError
        chars = data.decode("utf-8", errors="replace")
        return chars[0] if chars else None

    def _read_line_windows(self, timeout: Optional[float]) -> Optional[str]:
        import msvcrt

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if not msvcrt.kbhit():
                if deadline is not None:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        return None
                    time.sleep(min(0.01, max(0.0, left)))
                else:
                    time.sleep(0.01)
                continue
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            line = self._handle_char(char)
            if line is not None:
                return line

    def _handle_char(self, char: str) -> Optional[str]:
        """Feed one character.

        Returns the finished line once Enter is pressed (an empty line is a
        valid result), or ``None`` while the line is still being typed.
        """
        with self._lock:
            if char in ("\r", "\n"):
                # deactivate first: the line is finished, so the newline must
                # not be treated as background output that repaints the prompt
                self._active = False
                line = self._buffer
                self._buffer = ""
                self._console.echo("\n")
                return line
            if char == "\x03":
                self._active = False
                raise KeyboardInterrupt
            if char in ("\x04", "\x1a"):
                self._active = False
                raise EOFError
            if char in ("\x7f", "\x08"):
                if self._buffer:
                    self._buffer = self._buffer[:-1]
                    self._console.echo("\b \b")
                return None
            if char == "\x15":
                self._buffer = ""
                self._draw_input_line()
                return None
            if char < " ":
                return None
            self._buffer += char
            self._console.echo(char)
            return None


class Narrator:
    """Serialises slow "typed" output so two narrations never interleave."""

    def __init__(self, console: "Console") -> None:
        self._console = console
        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def say(self, text: str, speed: float = 1.0) -> None:
        if not text:
            return
        self._ensure_thread()
        self._idle.clear()
        self._queue.put((text.rstrip("\n"), speed))

    def flush(self, timeout: Optional[float] = 30.0) -> None:
        self._idle.wait(timeout)

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name="volt-narrator", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._idle.set()
                return
            text, speed = item
            try:
                self._print_slow(text, speed)
            finally:
                if self._queue.empty():
                    self._idle.set()

    def _print_slow(self, text: str, speed: float) -> None:
        multiplier = 1.0 - max(0.0, min(1.0, float(speed)))
        if multiplier <= 0.02:
            self._console.raw(text + "\n\n")
            return
        for char in text:
            self._console.raw(char)
            delay = 0.4 if char in _PUNCTUATION else 0.08
            time.sleep(delay * multiplier)
        self._console.raw("\n\n")


class Console:
    def __init__(self) -> None:
        _force_utf8()
        _enable_windows_vt()
        self.color = _supports_color()
        self.lock = threading.RLock()
        self.input = ConsoleInput(self)
        if self.input._mode == "windows":
            _windows_console_mode()
        self.narrator = Narrator(self)
        self._t: Callable[..., str] = lambda key, fallback="": fallback
        self._t_error: Callable[[str], str] = lambda key: key

    # -- colours ------------------------------------------------------------

    def paint(self, text: str, *codes: str) -> str:
        if not self.color or not codes:
            return text
        return "".join(codes) + text + RESET

    def bold(self, text: str) -> str:
        return self.paint(text, BOLD)

    def dim(self, text: str) -> str:
        return self.paint(text, DIM)

    def red(self, text: str) -> str:
        return self.paint(text, RED)

    def green(self, text: str) -> str:
        return self.paint(text, GREEN)

    def yellow(self, text: str) -> str:
        return self.paint(text, YELLOW)

    def cyan(self, text: str) -> str:
        return self.paint(text, CYAN)

    def magenta(self, text: str) -> str:
        return self.paint(text, MAGENTA)

    # -- raw output ---------------------------------------------------------

    def raw(self, text: str, end: str = "") -> None:
        with self.lock:
            # The active input line is erased, then redrawn after the output so
            # background messages never garble what the player is typing.
            if self.input._active:
                sys.stdout.write("\r\x1b[2K")
            sys.stdout.write(text + end)
            sys.stdout.flush()
            if self.input._active:
                sys.stdout.write(self.input._prompt + self.input._buffer)
                sys.stdout.flush()

    def echo(self, text: str) -> None:
        """Write at the cursor without touching the prompt.

        Used for keystroke echo: the prompt is already on screen and the cursor
        sits right after it, so erasing and redrawing the line here would put
        the prompt behind the character.
        """
        with self.lock:
            sys.stdout.write(text)
            sys.stdout.flush()

    def line(self, text: str = "") -> None:
        self.raw(text, "\n")

    def blank(self) -> None:
        self.line()

    def rule(self, title: str = "") -> None:
        width = min(64, max(24, _terminal_width() - 2))
        if title:
            head = "-- %s " % title
            self.line(self.dim(head + "-" * max(0, width - len(head))))
        else:
            self.line(self.dim("-" * width))

    def clear(self) -> None:
        with self.lock:
            sys.stdout.write("\x1b[2J\x1b[0;0H")
            sys.stdout.flush()

    def narrate(self, text: str, speed: float = 1.0) -> None:
        if not text:
            return
        self.narrator.say(text, speed)

    def flush_narration(self, timeout: Optional[float] = 30.0) -> None:
        self.narrator.flush(timeout)

    # -- prompts ------------------------------------------------------------

    def ask(self, prompt: str, timeout: Optional[float] = None) -> Optional[str]:
        self.input.prompt(prompt)
        line = self.input.read_line(timeout)
        if line is not None:
            self.blank()
        return line

    def ask_int(
        self,
        prompt: str,
        minimum: Optional[int] = None,
        maximum: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Optional[int]:
        while True:
            line = self.ask(prompt, timeout)
            if line is None:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                value = int(line)
            except ValueError:
                self.error(self.t_error("not_a_number"))
                continue
            if minimum is not None and value < minimum:
                self.error("  %s >= %s" % (self.t_error("too_small"), minimum))
                continue
            if maximum is not None and value > maximum:
                self.error("  %s <= %s" % (self.t_error("too_big"), maximum))
                continue
            return value

    def ask_bool(self, prompt: str, default: Optional[bool] = None) -> bool:
        hint = "[y/n]"
        if default is not None:
            hint = "[Y/n]" if default else "[y/N]"
        while True:
            line = self.ask("%s %s " % (prompt, self.dim(hint)))
            if line is None:
                line = ""
            answer = line.strip().lower()
            if not answer and default is not None:
                return default
            if answer in ("y", "yes", "д", "да", "1", "true"):
                return True
            if answer in ("n", "no", "н", "нет", "0", "false"):
                return False

    def ask_text(self, prompt: str, allow_empty: bool = False) -> str:
        while True:
            line = self.ask(prompt)
            if line is None:
                line = ""
            value = line.strip()
            if value or allow_empty:
                return value

    def ask_multiline(self, prompt: str, end_marker: str = ".") -> str:
        self.line(prompt)
        collected: list = []
        while True:
            line = self.ask(self.dim("  > "))
            if line is None:
                line = ""
            stripped = line.strip()
            if not stripped or stripped == end_marker:
                break
            collected.append(stripped)
        self.blank()
        return "\n".join(collected)

    # -- messages -----------------------------------------------------------

    def info(self, text: str) -> None:
        self.line("%s %s" % (self.cyan(">>"), text))

    def ok(self, text: str) -> None:
        self.line("%s %s" % (self.green("ok"), text))

    def warn(self, text: str) -> None:
        self.line("%s %s" % (self.yellow("!"), text))

    def error(self, text: str) -> None:
        self.line("%s %s" % (self.red("x"), text))

    def hint(self, text: str) -> None:
        self.line(self.dim(text))

    def kv(self, key: str, value: str, width: int = 22) -> None:
        self.line("  %s %s" % (self.dim(key.ljust(width)), value))

    def bullets(self, items: Iterable[str]) -> None:
        for item in items:
            self.line("  %s %s" % (self.dim("-"), item))

    def numbered(self, entries: Sequence[str], start: int = 1) -> None:
        for index, entry in enumerate(entries, start):
            self.line("  %s %s" % (self.magenta(str(index) + ")"), entry))

    # -- animation ----------------------------------------------------------

    def spinner_run(
        self,
        work: Callable[[], object],
        message: str,
    ) -> object:
        """Run ``work`` in a thread while animating a spinner."""
        result: list = []
        error: list = []

        def target() -> None:
            try:
                result.append(work())
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                error.append(exc)

        thread = threading.Thread(target=target, name="volt-task", daemon=True)
        thread.start()
        frames = "|/-\\"
        index = 0
        try:
            while thread.is_alive():
                self.raw("\r%s %s" % (frames[index % len(frames)], message))
                index += 1
                time.sleep(0.12)
            thread.join()
        finally:
            self.raw("\r\x1b[2K")
        if error:
            raise error[0]
        return result[0] if result else None

    # -- localisation hook --------------------------------------------------

    def bind_locale(
        self,
        t: Callable[..., str],
        t_error: Callable[[str], str],
    ) -> None:
        self._t = t
        self._t_error = t_error

    def t(self, key: str, fallback: str = "") -> str:
        return self._t(key, fallback)

    def t_error(self, key: str) -> str:
        return self._t_error(key)


def _terminal_width() -> int:
    try:
        return max(40, os.get_terminal_size().columns)
    except OSError:
        return 80


console = Console()