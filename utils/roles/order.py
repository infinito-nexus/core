"""Resolve the roles of a group into their run_after order.

The play used to consume a task file per group, generated at setup time. The
order is derived from data that already lives in the roles, so it is resolved
here instead and read through the `group_roles` lookup.
"""

from __future__ import annotations

from collections import defaultdict, deque
from functools import cache
from pathlib import Path
from typing import Any

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_VARS_MAIN


def find_roles(roles_dir: str | Path, prefixes: list[str] | None = None):
    """Yield ``(role_path, meta_file)`` for every role matching *prefixes*.

    Args:
        roles_dir: directory holding the role folders.
        prefixes: name prefixes to keep; all roles when empty or None.
    """
    for path in sorted(Path(roles_dir).iterdir()):
        if prefixes and not any(
            path.name.startswith(pref) or path.name == pref.rstrip("-")
            for pref in prefixes
        ):
            continue
        meta_file = path / ROLE_FILE_META_MAIN
        if path.is_dir() and meta_file.is_file():
            yield path, meta_file


def load_run_after(meta_file: str | Path) -> list[str]:
    """Return the run_after list declared by the role owning *meta_file*."""
    from utils.roles.meta_lookup import get_role_run_after

    role_path = Path(meta_file).parent.parent.resolve()
    try:
        return get_role_run_after(str(role_path), role_name=role_path.name)
    except Exception:  # noqa: BLE001  a role without readable run_after simply has none
        return []


def load_application_id(role_path: str | Path) -> str | None:
    """Return the application_id from the role's vars/main.yml, or None."""
    vars_file = Path(role_path) / ROLE_FILE_VARS_MAIN
    if vars_file.exists():
        return load_yaml(str(vars_file)).get("application_id")
    return None


def build_dependency_graph(roles_dir: str | Path, prefixes: list[str] | None = None):
    """Return ``(graph, in_degree, roles)`` over the roles matching *prefixes*.

    Only run_after edges pointing inside the selected set become edges, so a
    group resolves independently of the roles outside it.
    """
    graph: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = defaultdict(int)
    roles: dict[str, dict[str, Any]] = {}

    role_entries = list(find_roles(roles_dir, prefixes))
    in_scope = {path.name for path, _ in role_entries}

    for role_path, meta_file in role_entries:
        role_name = role_path.name
        in_scope_deps = [d for d in load_run_after(meta_file) if d in in_scope]

        roles[role_name] = {
            "role_name": role_name,
            "run_after": in_scope_deps,
            "application_id": load_application_id(role_path),
            "path": str(role_path),
        }

        for dependency in in_scope_deps:
            graph[dependency].append(role_name)
            in_degree[role_name] += 1

        if role_name not in in_degree:
            in_degree[role_name] = 0

    return graph, in_degree, roles


def find_cycle(roles: dict[str, dict[str, Any]]) -> list[str] | None:
    """Return a run_after cycle as a role list with the start repeated, or None."""
    visited: set[str] = set()
    stack: set[str] = set()

    def dfs(node: str, path: list[str]) -> list[str] | None:
        visited.add(node)
        stack.add(node)
        path.append(node)
        for dep in roles.get(node, {}).get("run_after", []):
            if dep not in visited:
                found = dfs(dep, path)
                if found:
                    return found
            elif dep in stack:
                return [*path[path.index(dep) :], dep]
        stack.remove(node)
        path.pop()
        return None

    for role in roles:
        if role not in visited:
            cycle = dfs(role, [])
            if cycle:
                return cycle
    return None


def topological_sort(graph, in_degree, roles=None) -> list[str]:
    """Return the role names in run_after order.

    Raises:
        RuntimeError: when the graph does not resolve, naming the cycle and the
            roles left unsorted so the failure is actionable.
    """
    queue = deque([r for r, d in in_degree.items() if d == 0])
    sorted_roles: list[str] = []
    local_in = dict(in_degree)

    while queue:
        role = queue.popleft()
        sorted_roles.append(role)
        for nbr in graph.get(role, []):
            local_in[nbr] -= 1
            if local_in[nbr] == 0:
                queue.append(nbr)

    if len(sorted_roles) != len(in_degree):
        cycle = find_cycle(roles or {})
        unsorted = [r for r in in_degree if r not in sorted_roles]

        reason = (
            f"Circular dependency detected: {' -> '.join(cycle)}"
            if cycle
            else "Unresolved dependencies among roles (possible cycle or missing role)."
        )
        details = []
        if unsorted:
            details.append("Unsorted roles and their declared run_after dependencies:")
            details += [
                f"  - {r} depends on {roles.get(r, {}).get('run_after', [])!r}"
                for r in unsorted
            ]

        raise RuntimeError(
            "\n".join(
                [
                    "❌ Dependency resolution failed",
                    reason,
                    *details,
                    f"Full dependency graph: {dict(graph)!r}",
                ]
            )
        )

    return sorted_roles


@cache
def ordered_roles(roles_dir: str, group: str) -> tuple[dict[str, str], ...]:
    """Return ``({'role': …, 'app': …}, …)`` for *group*, in run_after order.

    Args:
        roles_dir: directory holding the role folders.
        group: group name without the trailing dash, e.g. ``web-app``.

    Raises:
        ValueError: when a role in the group declares no application_id.
    """
    graph, in_degree, roles = build_dependency_graph(roles_dir, [f"{group}-"])

    entries = []
    for role_name in topological_sort(graph, in_degree, roles):
        role = roles[role_name]
        if role.get("application_id") is None:
            vars_file = Path(role["path"]) / ROLE_FILE_VARS_MAIN
            raise ValueError(f"'application_id' missing in {vars_file}")
        entries.append({"role": role_name, "app": role["application_id"]})

    return tuple(entries)
