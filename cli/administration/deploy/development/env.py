from __future__ import annotations

import os

from utils.distros import distro_names

VALID_DISTROS: tuple[str, ...] = distro_names()


def compose_file_args() -> list[str]:
    """Compose `-f` flags shared by up and down flows.

    Each override is gated on the resource it needs being present, not on the
    instance slot: an override whose `:?` guard is unsatisfied would abort the
    stack outright, so a checkout that was never handed a shared git dir or
    cache network simply does not layer that file in.
    """
    from .profile import Profile

    profile = Profile()
    out = ["-f", "compose.yml"]
    if profile.shared_git_dir():
        out += ["-f", "compose/worktree.override.yml"]
    if profile.cache_stack_enabled():
        out += ["-f", "compose/cache.override.yml"]
        if profile.shared_cache_network():
            out += ["-f", "compose/cache.shared.override.yml"]
    if (os.environ.get("INFINITO_PUBLISH_PORTS") or "").strip().lower() == "false":
        out += ["-f", "compose/noports.override.yml"]
    return out


def resolve_distro() -> str:
    """Return INFINITO_DISTRO; raise SystemExit if missing or invalid."""
    distro = os.environ["INFINITO_DISTRO"].strip()
    if not distro:
        raise SystemExit(
            "INFINITO_DISTRO is not set. Run 'make dotenv' (or source scripts/meta/env/load.sh) "
            f"or export INFINITO_DISTRO=<{'|'.join(VALID_DISTROS)}> "
            "before invoking cli.administration.deploy.development."
        )
    if distro not in VALID_DISTROS:
        raise SystemExit(
            f"INFINITO_DISTRO={distro!r} is not a valid distro. "
            f"Valid: {', '.join(VALID_DISTROS)}."
        )
    return distro
