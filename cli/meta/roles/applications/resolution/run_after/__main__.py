#!/usr/bin/env python3
"""
Resolve run_after transitively for a given role.

Per ``run_after`` lives at
``meta/services.yml.<primary_entity>.run_after``. This script delegates to
:func:`utils.roles.meta_lookup.get_role_run_after` so the primary-entity
derivation stays in one place.

Usage:
  python -m cli.meta.roles.applications.resolution.run_after <role_name>

Output:
  All resolved run_after role names separated by whitespaces (one line).
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from utils.roles.meta_lookup import (
    MetaServicesShapeError,
    get_role_run_after,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path


class RunAfterResolutionError(RuntimeError):
    """Raised when run_after resolution fails (e.g., cycle detected)."""


def roles_dir() -> Path:
    return PROJECT_ROOT / "roles"


def load_run_after(role_name: str) -> list[str]:
    """Return the role's ``run_after`` list (or ``[]`` when absent).

    Reads from ``meta/services.yml.<primary_entity>.run_after``.
    """
    role_dir = roles_dir() / role_name
    if not role_dir.is_dir():
        return []
    try:
        return get_role_run_after(role_dir, role_name=role_name)
    except MetaServicesShapeError as exc:
        raise RunAfterResolutionError(
            f"Invalid run_after in roles/{role_name}/meta/services.yml: {exc}"
        ) from exc


def resolve_run_after_transitively(start_role: str) -> list[str]:
    """
    Resolve run_after dependencies recursively (run_after of run_after, ...).

    - Detects cycles and raises RunAfterResolutionError on infinite loops.
    - Returns a topologically ordered list (prerequisites first).
    - The start_role itself is NOT included in the result.
    """
    rdir = roles_dir()
    if not (rdir / start_role).is_dir():
        raise RunAfterResolutionError(
            f"Unknown role: {start_role!r} (missing folder {rdir / start_role})"
        )

    # Cache run_after lists per role for speed and consistent error reporting
    cache: dict[str, list[str]] = {}

    def ra(role: str) -> list[str]:
        if role not in cache:
            # Validate role existence when it is referenced
            if not (rdir / role).is_dir():
                raise RunAfterResolutionError(
                    f"Invalid run_after reference: {role!r} (missing folder {rdir / role})"
                )
            cache[role] = load_run_after(role)
        return cache[role]

    visited: set[str] = set()
    stack: list[str] = []
    out: list[str] = []

    def dfs(node: str) -> None:
        if node in stack:
            # Cycle: show a readable path: A -> B -> C -> A
            idx = stack.index(node)
            cycle = [*stack[idx:], node]
            raise RunAfterResolutionError(
                f"Circular run_after dependency detected: {' -> '.join(cycle)}"
            )

        if node in visited:
            return

        visited.add(node)
        stack.append(node)

        for dep in ra(node):
            dfs(dep)

        stack.pop()

        # Post-order append yields a valid prerequisites-first ordering.
        if node != start_role:
            out.append(node)

    dfs(start_role)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve all galaxy_info.run_after dependencies of a role transitively."
    )
    parser.add_argument(
        "role_name", help="Name of the role folder under ./roles (e.g., web-app-taiga)"
    )
    args = parser.parse_args()

    resolved = resolve_run_after_transitively(args.role_name)
    print(" ".join(resolved))


if __name__ == "__main__":
    main()
