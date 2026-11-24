"""Terminal output helpers: colors, prompts and small tables."""

from __future__ import annotations

import os
import sys
import time
from typing import Iterable, List, Optional, Sequence

from .i18n import tr

_COLOR: Optional[bool] = None


def setup_streams() -> None:
    """Never crash on characters the console code page cannot show."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


# Make every print safe from the first import on (pipes on Windows default to cp1252).
setup_streams()


def _color_enabled() -> bool:
    global _COLOR
    if _COLOR is not None:
        return _COLOR
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        _COLOR = False
        return _COLOR
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                _COLOR = True
            else:
                _COLOR = False
        except Exception:
            _COLOR = False
    else:
        _COLOR = True
    return _COLOR


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _color_enabled() else text


def bold(text: str) -> str:
    return _c(text, "1")


def dim(text: str) -> str:
    return _c(text, "2")


def green(text: str) -> str:
    return _c(text, "32")


def red(text: str) -> str:
    return _c(text, "31")


def yellow(text: str) -> str:
    return _c(text, "33")


def cyan(text: str) -> str:
    return _c(text, "36")


def say(msg: str = "") -> None:
    print(msg, flush=True)


def ok(msg: str) -> None:
    print(green("✔ ") + msg, flush=True)


def warn(msg: str) -> None:
    print(yellow("! ") + msg, flush=True)


def error(msg: str) -> None:
    print(red("✘ ") + msg, file=sys.stderr, flush=True)


def step(msg: str) -> None:
    print(cyan("→ ") + msg, flush=True)


def heading(msg: str) -> None:
    line = "─" * max(20, min(60, len(msg) + 4))
    print()
    print(bold(msg))
    print(dim(line), flush=True)


def interactive() -> bool:
    return sys.stdin.isatty() and not os.environ.get("ALLINONE_NONINTERACTIVE")


def ask(prompt: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default or ""
    return value if value else (default or "")


def confirm(prompt: str, default: bool = True) -> bool:
    if not interactive():
        return default
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"{prompt} [{hint}]: ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes", "ن", "نعم", "1", "ok")


def table(rows: Sequence[Sequence[str]], headers: Optional[Sequence[str]] = None) -> None:
    data: List[List[str]] = [list(map(str, r)) for r in rows]
    if headers:
        data.insert(0, list(headers))
    if not data:
        return
    widths = [max(len(_strip_ansi(r[i])) for r in data if i < len(r)) for i in range(max(len(r) for r in data))]
    for idx, row in enumerate(data):
        cells = []
        for i, cell in enumerate(row):
            pad = widths[i] - len(_strip_ansi(cell))
            cells.append(cell + " " * pad)
        line = "  ".join(cells).rstrip()
        print(bold(line) if headers and idx == 0 else line)


def pad(text: str, width: int) -> str:
    """Left-align text that may contain color codes."""
    return text + " " * max(0, width - len(_strip_ansi(text)))


def _strip_ansi(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        if text[i] == "\033":
            j = text.find("m", i)
            if j != -1:
                i = j + 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


class Waiter:
    """A one-line progress indicator for slow waits (gateway startup, downloads)."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str):
        self.label = label
        self.start = time.time()
        self.i = 0
        self.tty = sys.stdout.isatty()
        if not self.tty:
            print(label + " ...", flush=True)

    def tick(self, extra: str = "") -> None:
        if not self.tty:
            return
        frame = self.FRAMES[self.i % len(self.FRAMES)]
        self.i += 1
        secs = int(time.time() - self.start)
        import shutil

        width = max(20, shutil.get_terminal_size((80, 20)).columns - 1)
        line = f"{frame} {self.label} {secs}s {extra}"[:width]
        sys.stdout.write("\r" + cyan(line[:1]) + line[1:])
        sys.stdout.flush()

    def done(self, msg: Optional[str] = None, success: bool = True) -> None:
        if self.tty:
            import shutil

            width = max(20, shutil.get_terminal_size((80, 20)).columns - 1)
            sys.stdout.write("\r" + " " * width + "\r")
            sys.stdout.flush()
        if msg:
            (ok if success else error)(msg)


def tail_lines(path, n: int = 30) -> List[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 64 * 1024))
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return data.splitlines()[-n:]


def print_block(lines: Iterable[str]) -> None:
    for line in lines:
        print(dim("  │ ") + line)
