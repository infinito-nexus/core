from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from utils.roles.meta_lookup import get_role_requires_devices

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from cli.administration.deploy.development.compose import Compose

REPORT = "requires-devices"
DECLINED = "declined"
SUMMARY_KEY = "GITHUB_STEP_SUMMARY"


def required_devices(roles_dir: Path, role_ids: Sequence[str]) -> dict[str, list[str]]:
    """Args:
        roles_dir: the repository's ``roles`` directory.
        role_ids: the roles a deploy round runs.

    Returns:
        Every device the roles name in ``requires_devices``, mapped to the roles
        that need it, both in the order the round names them.
    """
    needs: dict[str, list[str]] = {}
    for role in role_ids:
        for device in get_role_requires_devices(roles_dir / role, role_name=role):
            needs.setdefault(device, []).append(role)
    return needs


def missing_devices(compose: Compose, devices: Sequence[str]) -> list[str]:
    """Args:
        compose: the stack whose ``infinito`` container the deploy runs on.
        devices: device paths the round needs.

    Returns:
        The devices that are no character device on the deploy target.
    """
    return [
        device
        for device in devices
        if compose.exec(
            ["test", "-c", device], check=False, capture=True, tty=False
        ).returncode
        != 0
    ]


def decline(
    needs: Mapping[str, Sequence[str]], missing: Sequence[str], round_label: str
) -> None:
    """Args:
    needs: every device of the round, mapped to the roles that need it.
    missing: the devices the deploy target lacks.
    round_label: the round as ``<n>/<total>``.
    """
    lines = []
    for device in missing:
        roles = ",".join(needs[device])
        print(
            f"{REPORT}: status={DECLINED} device={device} roles={roles}"
            f" round={round_label} reason=the deploy target has no {device},"
            " so this round and every later one are not run"
        )
        lines.append(
            f"- `{roles}` round {round_label}: **not run** ({DECLINED}),"
            f" the deploy target has no `{device}`"
        )
    summary = os.environ.get(SUMMARY_KEY)
    if not summary:
        return
    with Path(summary).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
