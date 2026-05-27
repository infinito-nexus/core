"""Output and subprocess helpers."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def section(title: str, *, file=None) -> None:
    print(f"\n=== {title} ===", flush=True, file=file or sys.stdout)


def line(label: str, value: str, *, file=None) -> None:
    print(f"  {label}: {value}", flush=True, file=file or sys.stdout)


def cmd_capture(argv: Sequence[str], timeout: float = 5.0) -> tuple[int, str]:
    """Run argv and return (returncode, combined stdout+stderr).

    Returns (-1, "command not found: …") when the binary is missing.
    Returns (-2, "timeout after …") when the call exceeds ``timeout``.
    """
    try:
        p = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return -1, f"command not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return -2, f"timeout after {timeout}s: {' '.join(argv)}"
