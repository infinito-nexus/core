from __future__ import annotations

import signal
import subprocess
import sys

from .navigation import prompt


def clear_screen() -> None:
    if not sys.stdout.isatty():
        return
    # 2J clears the visible viewport, 3J wipes the scrollback buffer
    # (xterm extension supported by every modern terminal), H homes the
    # cursor. Together they leave a fresh frame for the next command's
    # output instead of a stack of prior runs.
    print("\033[3J\033[2J\033[H", end="", flush=True)


def run_cli(argv: list[str], *, current: list[str] | None = None) -> int:
    clear_screen()
    if current is not None and sys.stdout.isatty():
        print(f"{prompt(current)}{' '.join(argv)}")
    prev_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return subprocess.run(
            [sys.executable, "-m", "cli", *argv], check=False
        ).returncode
    finally:
        signal.signal(signal.SIGINT, prev_handler)
