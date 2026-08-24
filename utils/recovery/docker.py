"""Ask the docker daemon what a replay is allowed to touch.

Split out of :mod:`utils.recovery.databases` so the replay module carries the
generation's layout and the credentials, and this one the probing: which
container serves a volume, which compose project it belongs to, and who is
still running in it.
"""

from __future__ import annotations

import subprocess

DOCKER_BIN = "docker"


class RecoveryError(Exception):
    """A condition that makes the replay unprovable."""


def _docker(argv: list[str], docker_host: str | None) -> list[str]:
    return [DOCKER_BIN, *(["-H", docker_host] if docker_host else []), *argv]


def _run(argv: list[str], secret: str = "") -> str:
    """Run a command, aborting the replay when it fails.

    Args:
        argv: the command.
        secret: a value to redact from the error message.
    """
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError as missing:
        raise RecoveryError(f"{argv[0]} is not on PATH") from missing
    if result.returncode != 0:
        shown = " ".join(argv)
        if secret:
            shown = shown.replace(secret, "***")
        raise RecoveryError(
            f"command failed ({result.returncode}): {shown}\n{result.stderr.strip()}"
        )
    return result.stdout


def container_of_volume(volume: str, docker_host: str | None = None) -> str:
    """Name the running container that mounts a volume.

    Raises:
        RecoveryError: nothing is running to replay into. A dump reaches its
            database through ``docker exec``, so unlike a file tree it cannot
            be restored onto a bare host - the engine has to be up. The two
            ways to get there differ, so they are reported apart.
    """
    listed = _docker(
        ["ps", "--filter", f"volume={volume}", "--format", "{{.Names}}"], docker_host
    )
    running = _run(listed).split()
    if running:
        return running[0]
    known = _run(
        _docker(
            ["ps", "-a", "--filter", f"volume={volume}", "--format", "{{.Names}}"],
            docker_host,
        )
    ).split()
    if known:
        raise RecoveryError(
            f"{known[0]} mounts volume {volume} but is not running; the dump is "
            "replayed through docker exec, so start that container first"
        )
    raise RecoveryError(
        f"no container mounts volume {volume} on this host; a dump can only be "
        "replayed into a running database service, so deploy the stack first "
        "and recover with the consumers stopped"
    )


def consumers_running(project: str, docker_host: str | None = None) -> list[str]:
    """List the running containers of one compose project."""
    return _run(
        _docker(
            [
                "ps",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Names}}",
            ],
            docker_host,
        )
    ).split()


def project_of(container: str, docker_host: str | None = None) -> str:
    """The compose project a container belongs to, empty when it has none."""
    return _run(
        _docker(
            [
                "inspect",
                "--type",
                "container",
                "-f",
                '{{index .Config.Labels "com.docker.compose.project"}}',
                container,
            ],
            docker_host,
        )
    ).strip()


def assert_no_consumers(
    project: str, docker_host: str | None = None, ignore: tuple[str, ...] = ()
) -> None:
    """Refuse to replay into a database whose application is still up.

    Args:
        project: the compose project to check.
        docker_host: remote docker endpoint, or None for this host.
        ignore: containers that are not consumers - the engine itself, when
            the project checked is the one the engine lives in.

    Raises:
        RecoveryError: the compose project still runs containers. A booting
            consumer recreates the pre-cleaned schema under the replay.
    """
    if not project:
        return
    still_up = [
        name for name in consumers_running(project, docker_host) if name not in ignore
    ]
    if still_up:
        raise RecoveryError(
            f"project '{project}' still runs {', '.join(still_up)}; a booting "
            "consumer recreates the pre-cleaned schema under the replay, so stop it first"
        )
