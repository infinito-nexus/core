"""Pinned-password validation: every user a host's roles need states a password."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cli.administration.inventory.provision.users_generator import (
    has_pinned_password,
    required_user_policies,
)

from .loaders import load_yaml_file, merged_variables


def _variable_files(root: Path, kind: str, name: str) -> list[Path]:
    single = root / kind / f"{name}.yml"
    files = [single] if single.is_file() else []
    return files + sorted((root / kind / name).glob("*.yml"))


def _walk(
    node: dict,
    lineage: tuple[str, ...],
    source: Path,
    hosts: dict[str, dict[str, Any]],
    group_vars: dict[str, dict],
) -> None:
    if isinstance(node.get("vars"), dict):
        group_vars.setdefault(lineage[-1] if lineage else "all", {}).update(
            node["vars"]
        )
    members = node.get("hosts")
    for host, inline in members.items() if isinstance(members, dict) else ():
        record = hosts.setdefault(
            str(host), {"source": source, "groups": {}, "inline": {}}
        )
        for depth, group in enumerate(lineage, 1):
            record["groups"][group] = max(depth, record["groups"].get(group, 0))
        if isinstance(inline, dict):
            record["inline"].update(inline)
    children = node.get("children")
    for group, body in children.items() if isinstance(children, dict) else ():
        _walk(
            body if isinstance(body, dict) else {},
            (*lineage, str(group)),
            source,
            hosts,
            group_vars,
        )


def _ordered(groups: dict[str, int]) -> list[str]:
    return sorted(groups, key=lambda group: (groups[group], group))


def _effective_users(
    root: Path,
    host: str,
    record: dict[str, Any],
    groups: list[str],
    group_vars: dict[str, dict],
) -> dict:
    """Return the ``users`` mapping Ansible resolves for one host.

    Args:
        root: the inventory directory.
        host: the inventory hostname.
        record: the host's source file, groups and inline variables.
        groups: the host's groups, shallowest first.
        group_vars: the variables the inventory files set inline per group.

    Returns:
        The ``users`` of the source with the highest precedence that sets it:
        a dict variable replaces the lower one whole, it is not merged.
    """
    layers = [
        group_vars.get("all", {}),
        *(group_vars.get(group, {}) for group in groups),
        merged_variables(_variable_files(root, "group_vars", "all")),
        *(merged_variables(_variable_files(root, "group_vars", g)) for g in groups),
        record["inline"],
        merged_variables(_variable_files(root, "host_vars", host)),
    ]
    effective: dict = {}
    for layer in layers:
        effective.update(layer)
    users = effective.get("users")
    return users if isinstance(users, dict) else {}


def validate_pinned_passwords(inv_dir, roles_dir) -> list[str]:
    """Report every host whose roles need a user the inventory pins no password for.

    Args:
        inv_dir: the inventory directory; every top-level ``*.yml`` with an
            ``all`` mapping counts as an inventory file.
        roles_dir: directory the roles live in.

    Returns:
        One message per host naming every required user without a password
        and the provision command that pins them.
    """
    root = Path(inv_dir)
    hosts: dict[str, dict[str, Any]] = {}
    group_vars: dict[str, dict] = {}
    for path in sorted(root.glob("*.yml")):
        data = load_yaml_file(path)
        tree = data.get("all") if isinstance(data, dict) else None
        if isinstance(tree, dict):
            _walk(tree, (), path, hosts, group_vars)

    errs: list[str] = []
    for host, record in sorted(hosts.items()):
        groups = _ordered(record["groups"])
        users = _effective_users(root, host, record, groups, group_vars)
        missing = [
            username
            for username in required_user_policies(Path(roles_dir), groups)
            if not has_pinned_password(users.get(username))
        ]
        if not missing:
            continue
        errs.append(
            f"{host}: no pinned password for "
            f"{', '.join(f'users.{username}' for username in missing)}; each falls "
            "back to a generated password that changes on every read. Pin them "
            f"with: infinito administration inventory provision {root} --host {host} "
            f"--include {','.join(groups) or '<application ids>'} "
            f"--inventory-file <scratch copy of {record['source']}> "
            "--vault-password-file <vault password file>"
        )
    return errs
