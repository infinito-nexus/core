#!/usr/bin/env python3
"""
Resolve Ansible role meta dependencies transitively for a given role,
but ONLY include dependencies that define an application_id in vars/main.yml.

Usage:
  python -m cli.meta.applications.dependencies_resolution <role_name>

Output:
  All resolved dependency role names separated by whitespaces (one line),
  ordered prerequisites-first (topological order).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Set

from utils.cache.yaml import load_yaml


class DependenciesResolutionError(RuntimeError):
    """Raised when dependencies resolution fails (e.g., cycle detected)."""


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[5]


def roles_dir() -> Path:
    return repo_root_from_here() / "roles"


def role_meta_path(role_name: str) -> Path:
    return roles_dir() / role_name / "meta" / "main.yml"


def role_vars_path(role_name: str) -> Path:
    return roles_dir() / role_name / "vars" / "main.yml"


def has_application_id(role_name: str) -> bool:
    """
    Return True if roles/<role_name>/vars/main.yml contains a non-empty application_id.
    """
    vars_path = role_vars_path(role_name)
    if not vars_path.exists():
        return False

    try:
        data = load_yaml(vars_path)
    except Exception as exc:
        raise DependenciesResolutionError(
            f"Failed to parse {vars_path}: {exc}"
        ) from exc

    app_id = data.get("application_id")
    return isinstance(app_id, str) and bool(app_id.strip())


def _extract_dependency_role_names(raw: object, *, meta_path: Path) -> List[str]:
    """
    Normalize dependencies to a list of role names.

    Supports:
      dependencies:
        - web-app-nginx
        - role: web-app-nextcloud
          vars: ...
    """
    if raw is None:
        return []

    if not isinstance(raw, list):
        raise DependenciesResolutionError(
            f"Invalid dependencies type in {meta_path}: expected list, got {type(raw).__name__}"
        )

    out: List[str] = []
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            if not name:
                raise DependenciesResolutionError(
                    f"Invalid dependency entry in {meta_path}: {item!r} (empty string)"
                )
            out.append(name)
            continue

        if isinstance(item, dict):
            role = item.get("role")
            if not isinstance(role, str) or not role.strip():
                raise DependenciesResolutionError(
                    f"Invalid dependency mapping in {meta_path}: {item!r} (missing/invalid 'role' key)"
                )
            out.append(role.strip())
            continue

        raise DependenciesResolutionError(
            f"Invalid dependency entry in {meta_path}: {item!r} "
            f"(expected string or mapping with 'role')"
        )

    return out


def load_dependencies(role_name: str) -> List[str]:
    """
    Read dependencies from roles/<role_name>/meta/main.yml.
    """
    meta = role_meta_path(role_name)
    if not meta.exists():
        return []

    try:
        data = load_yaml(meta)
    except Exception as exc:
        raise DependenciesResolutionError(f"Failed to parse {meta}: {exc}") from exc

    deps_raw = data.get("dependencies", None)
    return _extract_dependency_role_names(deps_raw, meta_path=meta)


def resolve_dependencies_transitively(start_role: str) -> List[str]:
    """
    Resolve dependencies recursively (dependencies of dependencies, ...),
    but only include roles that define application_id.

    - Detects cycles and raises DependenciesResolutionError on infinite loops.
    - Returns a topologically ordered list (prerequisites first).
    - The start_role itself is NOT included in the result.
    """
    rdir = roles_dir()
    if not (rdir / start_role).is_dir():
        raise DependenciesResolutionError(
            f"Unknown role: {start_role!r} (missing folder {rdir / start_role})"
        )

    cache: Dict[str, List[str]] = {}

    def deps(role: str) -> List[str]:
        if role not in cache:
            if not (rdir / role).is_dir():
                raise DependenciesResolutionError(
                    f"Invalid dependency reference: {role!r} (missing folder {rdir / role})"
                )
            cache[role] = load_dependencies(role)
        return cache[role]

    visited: Set[str] = set()
    stack: List[str] = []
    out: List[str] = []

    def dfs(node: str) -> None:
        if node in stack:
            idx = stack.index(node)
            cycle = stack[idx:] + [node]
            raise DependenciesResolutionError(
                f"Circular dependencies detected: {' -> '.join(cycle)}"
            )

        if node in visited:
            return

        visited.add(node)
        stack.append(node)

        for dep in deps(node):
            dfs(dep)

        stack.pop()

        # Only include if it is an application role
        if node != start_role and has_application_id(node):
            out.append(node)

    dfs(start_role)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve all meta/main.yml dependencies of a role transitively (only application roles)."
    )
    parser.add_argument(
        "role_name", help="Name of the role folder under ./roles (e.g., web-app-taiga)"
    )
    args = parser.parse_args()

    resolved = resolve_dependencies_transitively(args.role_name)
    print(" ".join(resolved))


if __name__ == "__main__":
    main()
