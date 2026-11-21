from __future__ import annotations

from functools import cache
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

WORKSPACE_PY = Path(__file__).resolve().parents[1] / "files" / "python" / "workspace.py"


@cache
def _workspace():
    spec = spec_from_file_location("semaphore_workspace_py", str(WORKSPACE_PY))
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def semaphore_workspace_releases(changelog: str, floor: str) -> list[str]:
    """Args:
        changelog: the ``CHANGELOG.md`` the platform runner image holds.
        floor: ``SEMAPHORE_WORKSPACE_CORE_FLOOR``.

    Returns:
        The releases ``workspace.py`` accepts for that changelog and floor,
        newest first, through its own parse and floor.
    """
    if not changelog.strip():
        raise ValueError("the platform runner image holds an empty CHANGELOG.md")
    workspace = _workspace()
    return workspace.shipping_releases(workspace.parse_releases(changelog), floor)


def semaphore_ssh_keypair(comment: str) -> dict[str, str]:
    """Args:
    comment: the comment of the public half, such as ``ws-<id>``.

    Returns:
        ``private``, an OpenSSH private key, and ``public``, its
        ``<type> <base64> <comment>`` line.
    """
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        .decode()
    )
    return {"private": private, "public": f"{public} {comment}"}


def semaphore_targets_env(pinned: list[dict]) -> str:
    """Args:
    pinned: ``WORKSPACE_TARGETS`` as ``workspace.py operation`` pinned it,
        ``[{host, port, address}]``.

    Returns:
        The comma-separated ``<host>:<port>`` pairs the workspace templates
        read, IPv6 hosts in brackets.
    """
    return ",".join(
        f"[{t['host']}]:{t['port']}"
        if ":" in str(t["host"])
        else f"{t['host']}:{t['port']}"
        for t in pinned
    )


def semaphore_workspace_uid(held: list, base: int) -> int:
    """Args:
    held: the UIDs the workspace runners of this host already hold.
    base: the first UID of the workspace runner range.

    Returns:
        The lowest UID from ``base`` up that no runner holds.
    """
    taken = {int(uid) for uid in held}
    uid = int(base)
    while uid in taken:
        uid += 1
    return uid


def semaphore_workspace_neighbours(lines: list, project: str) -> list[str]:
    """Args:
    lines: ``container ps`` lines ``<name> <compose project> <compose service>``.
    project: the compose project of the workspace runner.

    Returns:
        The names of every running container but the runner of ``project``.
    """
    names = []
    for line in lines:
        fields = line.split(" ")
        if fields[1:3] != [project, "runner"]:
            names.append(fields[0])
    return names


def semaphore_workspace_uid_findings(tops: list, runner_uid: int) -> list[str]:
    """Args:
    tops: the registered ``container top <name> -eo uid`` results, each with
        ``semaphore_workspace_container``, ``rc`` and ``stdout_lines``.
    runner_uid: the UID the workspace runner runs as.

    Returns:
        One sorted line per container that runs a process as ``runner_uid``;
        a container that stopped before its ``top`` is skipped.
    """
    uid = str(int(runner_uid))
    return sorted(
        f"{top['semaphore_workspace_container']} runs a process as UID {uid}"
        for top in tops
        if top["rc"] == 0 and uid in {line.strip() for line in top["stdout_lines"][1:]}
    )


class FilterModule:
    def filters(self):
        return {
            "semaphore_ssh_keypair": semaphore_ssh_keypair,
            "semaphore_targets_env": semaphore_targets_env,
            "semaphore_workspace_releases": semaphore_workspace_releases,
            "semaphore_workspace_neighbours": semaphore_workspace_neighbours,
            "semaphore_workspace_uid": semaphore_workspace_uid,
            "semaphore_workspace_uid_findings": semaphore_workspace_uid_findings,
        }
