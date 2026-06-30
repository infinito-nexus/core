from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

from ansible.errors import AnsibleFilterError


def _to_role_set(raw: Iterable[str] | str | None, var_name: str) -> set[str]:
    if raw is None:
        return set()

    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}

    try:
        return {str(item).strip() for item in raw if str(item).strip()}
    except TypeError as exc:
        raise AnsibleFilterError(
            f"{var_name} must be an iterable of role names or CSV string"
        ) from exc


def discover_cli_roles(
    playbook_dir: str,
    group_names: Iterable[str] | str | None = None,
    only_roles: Iterable[str] | str | None = None,
    skip_roles: Iterable[str] | str | None = None,
) -> list[str]:
    base = Path(playbook_dir) / "roles"
    if not base.exists():
        raise AnsibleFilterError(f"roles dir not found: {base}")

    groups = _to_role_set(group_names, "group_names")
    only = _to_role_set(only_roles, "only_roles")
    skip = _to_role_set(skip_roles, "skip_roles")

    found: list[str] = []

    # Marker for CLI-test-enabled roles: .../roles/<role>/templates/test.env.j2
    for env_file in base.rglob("templates/test.env.j2"):
        role_name = (
            env_file.parents[  # nocheck: project-root-import — navigating role dir
                1
            ].name
        )
        found.append(role_name)

    uniq = sorted(set(found))

    # Mirror application_allowed: only test roles deployed on this host
    if groups:
        uniq = [role for role in uniq if role in groups]
    if only:
        uniq = [role for role in uniq if role in only]
    if skip:
        uniq = [role for role in uniq if role not in skip]

    return uniq


class FilterModule:
    def filters(self):
        return {
            "discover_cli_roles": discover_cli_roles,
        }
