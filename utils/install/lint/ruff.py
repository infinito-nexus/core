"""Install the ruff version pinned in pyproject.toml so every environment matches.

The pin lives in ``[project.optional-dependencies].dev`` (one SPOT, Dependabot
keeps it current). Host venvs, the lint container and CI all read that same pin,
so a rule that is preview-gated in one release and stable in the next (e.g.
ISC004, or S310 firing on ``urllib.request.Request``) cannot disagree across
environments.
"""

from __future__ import annotations

import os
import subprocess
import tomllib

from utils.cache import PROJECT_ROOT
from utils.install.pip import install_pip_pkg
from utils.install.primitives import log, which

_PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _pinned_spec() -> str:
    """Return the ruff requirement string declared in pyproject's dev extras."""
    with _PYPROJECT.open("rb") as f:
        dev = tomllib.load(f)["project"]["optional-dependencies"]["dev"]
    for dep in dev:
        if dep == "ruff" or dep.startswith("ruff=="):
            return dep
    raise RuntimeError(
        "ruff is not declared in pyproject.toml [project.optional-dependencies].dev"
    )


def _installed_version() -> str | None:
    try:
        proc = subprocess.run(
            ["ruff", "--version"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    parts = proc.stdout.split()
    return parts[1] if len(parts) >= 2 else None


def ensure() -> None:
    """Install the pinned ruff, reinstalling whenever the found version drifts."""
    spec = os.environ.get("RUFF_PIP_SPEC") or _pinned_spec()
    want = spec.split("==", 1)[1] if "==" in spec else None
    if want is not None and _installed_version() == want:
        return

    log(f"Installing {spec} (found {_installed_version() or 'no ruff'}).")
    install_pip_pkg(spec)

    if not which("ruff"):
        raise RuntimeError(
            f"Command 'ruff' is still unavailable after installing {spec}."
        )
