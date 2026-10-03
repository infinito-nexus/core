from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from ansible.errors import AnsibleFilterError

from utils.roles.meta_lookup import get_role_provides
from utils.roles.order import build_dependency_graph, topological_sort

SSO_SERVICE = "sso"

if TYPE_CHECKING:
    from collections.abc import Iterable


def _to_role_set(raw: Iterable[str] | str | None, var_name: str) -> set[str]:
    if raw is None:
        return set()

    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except (ValueError, SyntaxError):
                parsed = None
            if isinstance(parsed, (list, tuple, set)):
                return {str(item).strip() for item in parsed if str(item).strip()}
        return {item.strip() for item in raw.split(",") if item.strip()}

    try:
        return {str(item).strip() for item in raw if str(item).strip()}
    except TypeError as exc:
        raise AnsibleFilterError(
            f"{var_name} must be an iterable of role names or CSV string"
        ) from exc


def _in_test_order(roles_dir: Path, roles: list[str]) -> list[str]:
    """Order *roles* for the Playwright stage.

    Every role is deployed before any spec runs, so the order only matters for
    state one spec creates for another. The identity provider's specs provision
    users that consumers log in with, so the role that ``provides: sso`` runs
    first even when it deploys late (Keycloak runs after its mail provider);
    the rest follow the deploy order resolved by ``utils.roles.order``.

    Args:
        roles_dir: directory holding the role folders.
        roles: role names to order, alphabetically sorted.

    Returns:
        The same roles: the sso provider first, then providers before their
        consumers; roles outside the resolved graph keep their alphabetical
        order at the end.
    """
    graph, in_degree, meta = build_dependency_graph(roles_dir)
    position = {
        role: index
        for index, role in enumerate(topological_sort(graph, in_degree, meta))
    }
    return sorted(
        roles,
        key=lambda role: (
            get_role_provides((roles_dir / role).resolve(), role_name=role)
            != SSO_SERVICE,
            position.get(role, len(position)),
            role,
        ),
    )


def discover_playwright_roles(
    playbook_dir: str,
    only_roles: Iterable[str] | str | None = None,
    skip_roles: Iterable[str] | str | None = None,
) -> list[str]:
    base = Path(playbook_dir) / "roles"
    if not base.exists():
        raise AnsibleFilterError(f"roles dir not found: {base}")

    only = _to_role_set(only_roles, "only_roles")
    skip = _to_role_set(skip_roles, "skip_roles")

    found: list[str] = []

    for env_file in base.rglob("templates/playwright.env.j2"):
        # nocheck: project-root-import  walking from a discovered glob match (<role>/templates/...) up to its role dir, not the repo root
        role_name = env_file.parents[1].name
        found.append(role_name)

    uniq = _in_test_order(base, sorted(set(found)))

    if only:
        uniq = [role for role in uniq if role in only]
    if skip:
        uniq = [role for role in uniq if role not in skip]

    return uniq


class FilterModule:
    def filters(self):
        return {
            "discover_playwright_roles": discover_playwright_roles,
        }
