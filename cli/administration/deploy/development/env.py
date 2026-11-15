from __future__ import annotations

import os

from utils.distros import distro_names

VALID_DISTROS: tuple[str, ...] = distro_names()

INFRA_CONSUMER = "compose/infra-consumer.override.yml"


def compose_file_args() -> list[str]:
    """Compose `-f` flags shared by up and down flows.

    Returns:
        The `-f` flags; the infra consumer override joins the machine-wide
        infra network whenever the cache stack is enabled.
    """
    from .extra_mounts import OVERRIDE, parse_mounts, write_mounts_override
    from .profile import Profile

    profile = Profile()
    out = ["-f", "compose.yml"]
    if profile.shared_git_dir():
        out += ["-f", "compose/worktree.override.yml"]
    if profile.cache_stack_enabled():
        out += ["-f", INFRA_CONSUMER]
        if profile.shared_package_cache():
            out += ["-f", "compose/shared-cache.override.yml"]
            if profile.host_pacman_cache():
                out += ["-f", "compose/pacman.override.yml"]
    if profile.gpu_reservable():
        out += ["-f", "compose/gpu.override.yml"]
    if (os.environ.get("INFINITO_PUBLISH_PORTS") or "").strip().lower() == "false":
        out += ["-f", "compose/noports.override.yml"]

    if profile.image_mirror_enabled():
        from utils.cache.files import PROJECT_ROOT

        from .runner_mirror import write_override

        out += ["-f", write_override(PROJECT_ROOT, out[1::2])]
    mounts = parse_mounts(os.environ.get("INFINITO_EXTRA_MOUNTS") or "")
    if mounts:
        from utils.cache.files import PROJECT_ROOT

        out += [
            "-f",
            write_mounts_override(
                PROJECT_ROOT, mounts, service="infinito", override=OVERRIDE
            ),
        ]
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
