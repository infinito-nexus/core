"""Require a fallback on ``<PREFIX>_PRIMARY_NODE`` delegation inside a
conditional block.

Ansible templates ``delegate_to`` before it evaluates ``when``. A task in a
``when``-gated block that delegates to a ``*_PRIMARY_NODE`` fact set by
``swarm/resolve/primary.yml`` earlier in the same block therefore fails with
"is undefined" whenever the block is skipped, e.g. on every standalone row.
Use ``{{ <PREFIX>_PRIMARY_NODE | default(STACK_HOST) }}``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_PRIMARY_NODE = re.compile(r"\b[A-Z][A-Z0-9_]*_PRIMARY_NODE\b")


def _unguarded(tasks, gated: bool) -> list[str]:
    found: list[str] = []
    if not isinstance(tasks, list):
        return found
    for task in tasks:
        if not isinstance(task, dict):
            continue
        inner_gated = gated or "when" in task
        for key in ("block", "rescue", "always"):
            found.extend(_unguarded(task.get(key), inner_gated))
        delegate = task.get("delegate_to")
        if (
            gated
            and isinstance(delegate, str)
            and _PRIMARY_NODE.search(delegate)
            and "default(" not in delegate
        ):
            found.append(str(task.get("name", delegate)))
    return found


def _violations() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted(Path(PROJECT_ROOT, "roles").glob("*/tasks/**/*.yml")):
        hits = _unguarded(load_yaml_any(path), gated=False)
        if hits:
            result[path.relative_to(PROJECT_ROOT).as_posix()] = hits
    return result


class TestPrimaryNodeDelegateDefault(unittest.TestCase):
    def test_gated_block_sibling_is_flagged(self) -> None:
        tasks = [
            {
                "when": "MARIADB_HA | bool",
                "block": [
                    {"name": "resolve", "include_tasks": "primary.yml"},
                    {"name": "apply", "delegate_to": "{{ MARIADB_PRIMARY_NODE }}"},
                ],
            }
        ]
        self.assertEqual(_unguarded(tasks, gated=False), ["apply"])

    def test_fallback_and_ungated_pass(self) -> None:
        tasks = [
            {"name": "ha-only file", "delegate_to": "{{ MARIADB_PRIMARY_NODE }}"},
            {
                "when": "MARIADB_HA | bool",
                "block": [
                    {
                        "name": "apply",
                        "delegate_to": "{{ MARIADB_PRIMARY_NODE | default(STACK_HOST) }}",
                    }
                ],
            },
        ]
        self.assertEqual(_unguarded(tasks, gated=False), [])

    def test_no_unguarded_primary_node_delegation(self) -> None:
        found = _violations()
        if found:
            self.fail(
                "delegate_to a *_PRIMARY_NODE fact inside a when-gated block "
                "without a default. Ansible templates delegate_to before when, "
                "so the skipped block fails. Add '| default(STACK_HOST)'.\n"
                + "\n".join(
                    f"- {p}: {', '.join(names)}" for p, names in sorted(found.items())
                )
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
