"""Runtime-context lookups for the .env generator.

Each helper resolves a single piece of information from the host the
generator runs on (disk free space, RAM, hostname, /proc/version,
GitHub Actions env vars, ...). They are intentionally tiny and
side-effect-free apart from the OS read they need to perform, so they
can be exercised independently in tests.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
from pathlib import Path


def is_user_writable(path: str) -> bool:
    """Return True when `path` (or its closest existing ancestor) can
    be written to by the current user without privilege escalation.

    Used to decide between a system path (e.g. ``/opt/venvs``) and a
    user-local fallback (``$HOME/.venvs``) when the system path is not
    yet prepared on a fresh dev machine."""
    p = Path(path)
    while not p.exists() and str(p) not in ("/", "."):
        p = p.parent
    return os.access(p, os.W_OK)


def df_avail_gb(path: str) -> int:
    """Return free space in GB at `path` (or the closest existing
    ancestor). 0 when `df` fails or the output is unparseable."""
    p = Path(path)
    while not p.exists() and str(p) not in ("/", "."):
        p = p.parent
    try:
        out = subprocess.check_output(
            ["df", "--output=avail", "-B1G", str(p)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        return 0
    lines = out.strip().splitlines()
    if len(lines) < 2:
        return 0
    try:
        return int(lines[1].strip())
    except ValueError:
        return 0


def mem_available_mb() -> int:
    """`MemAvailable` from /proc/meminfo in MB. 0 on failure."""
    try:
        text = Path(
            "/proc/meminfo"
        ).read_text()  # nocheck: cache-read -- live kernel pseudo-file
    except OSError:
        return 0
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            try:
                kb = int(line.split()[1])
                return kb // 1024
            except (IndexError, ValueError):
                return 0
    return 0


def is_wsl2() -> bool:
    """True when /proc/version mentions microsoft or wsl. False otherwise."""
    try:
        text = Path(
            "/proc/version"
        ).read_text()  # nocheck: cache-read -- live kernel pseudo-file
    except OSError:
        return False
    return bool(re.search(r"microsoft|wsl", text, re.IGNORECASE))


def detect_gha_act() -> tuple[bool, bool]:
    """Return (running_on_github, running_on_act).

    Mirrors the legacy scripts/meta/env/runtime.sh logic:
      - GITHUB_ACTIONS=true AND ACT=true  -> act (local nektos act)
      - GITHUB_ACTIONS=true AND not ACT   -> real github actions
    """
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    act = gha and os.environ.get("ACT") == "true"
    return (gha and not act, act)


def hostname() -> str:
    """`socket.gethostname()` with a `local` fallback for sandboxed hosts
    that fail the syscall."""
    try:
        name = socket.gethostname()
    except OSError:
        return "local"
    return name or "local"


def run_helper(
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> str:
    """Run an existing shell helper, return stripped stdout. Empty
    string on failure. Helpers run with `cwd` as their working
    directory."""
    env = {**os.environ, **(extra_env or {})}
    try:
        out = subprocess.check_output(
            cmd, cwd=str(cwd), env=env, text=True, stderr=subprocess.DEVNULL
        )
        return out.strip()
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        return ""
