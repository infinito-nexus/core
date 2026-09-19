"""Register the emulation an architecture-pinned deploy needs."""

from __future__ import annotations

import argparse
import os
import platform
import subprocess

PROBE_IMAGE = "alpine:3"
INSTALLER_IMAGE = "tonistiigi/binfmt"

_HOST_ALIASES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}


def host_architecture() -> str:
    machine = platform.machine().lower()
    return _HOST_ALIASES.get(machine, machine)


def _can_execute(architecture: str) -> bool:
    return (
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                f"linux/{architecture}",
                PROBE_IMAGE,
                "true",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def ensure(platform_ref: str | None = None) -> None:
    """No-op when nothing is pinned or it is the host's own; raises SystemExit
    when the handler cannot be registered."""
    raw = (
        platform_ref
        if platform_ref is not None
        else os.environ.get("INFINITO_DOCKER_PLATFORM")
    )
    pinned = (raw or "").strip()
    if not pinned:
        return

    architecture = pinned.rsplit("/", 1)[-1]
    if architecture == host_architecture() or _can_execute(architecture):
        return

    print(f">>> Registering binfmt emulation for {pinned}")
    subprocess.run(
        [
            "docker",
            "run",
            "--privileged",
            "--rm",
            INSTALLER_IMAGE,
            "--install",
            architecture,
        ],
        stdout=subprocess.DEVNULL,
        check=False,
    )

    if not _can_execute(architecture):
        raise SystemExit(
            f"linux/{architecture} still cannot execute after registering a handler. "
            "Check whether this host permits --privileged containers."
        )


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "binfmt", help="Make an architecture executable here through emulation."
    )
    p.add_argument(
        "--architecture",
        default="",
        help="amd64 | arm64; empty takes the platform from INFINITO_DOCKER_PLATFORM.",
    )
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    named = args.architecture.strip()
    ensure(f"linux/{named}" if named else None)
    return 0
