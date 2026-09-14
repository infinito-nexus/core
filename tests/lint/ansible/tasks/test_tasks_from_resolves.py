"""A ``tasks_from`` entrypoint, and everything it includes, must resolve.

``tasks_from`` names a file inside the *called* role's ``tasks/`` directory and
is resolved at runtime, so a moved or mistyped target survives ansible-lint,
``--syntax-check`` and both sibling include lints, which only follow
``include_tasks``/``import_tasks``. The play then dies mid-deploy, after
everything before it has already run.

The second rule covers the trap that follows from the first. Ansible resolves a
relative ``include_tasks`` against the *including file's* directory when that
file was itself reached by path, but against ``tasks/`` when it was reached
through ``tasks_from``. So ``tasks/utils/mcp.yml`` may include ``mcp/probe.yml``
for as long as only its own role includes it, and breaks the day a caller
reaches it through ``tasks_from`` instead. The same file, unchanged, resolves
differently depending on the caller. Nested includes below a ``tasks_from``
entrypoint are therefore required to name a path that holds under both bases.

Templated names and templated targets are skipped: what they resolve to is not
knowable statically.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: tasks-from-resolves`` on, or directly above, the ``tasks_from`` line.
* ``# nocheck: tasks-from-nested-include`` on, or directly above, the include line.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

_RULE = "tasks-from-resolves"
_NESTED_RULE = "tasks-from-nested-include"
_INCLUDE_ROLE_KEYS = (
    "include_role",
    "ansible.builtin.include_role",
    "import_role",
    "ansible.builtin.import_role",
)
_INCLUDE_TASKS_KEYS = (
    "include_tasks",
    "ansible.builtin.include_tasks",
    "import_tasks",
    "ansible.builtin.import_tasks",
)


def _walk_tasks(node: object):
    """Yield every task mapping, descending into block/rescue/always."""
    if isinstance(node, list):
        for item in node:
            yield from _walk_tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            child = node.get(key)
            if child:
                yield from _walk_tasks(child)


def _include_role_args(task: dict) -> dict | None:
    for key in _INCLUDE_ROLE_KEYS:
        args = task.get(key)
        if isinstance(args, dict):
            return args
    return None


def _iter_entrypoints():
    """Yield ``(caller, role, target)``; ``role`` is None when it is templated.

    A templated role name is the reconciliation case: the caller loops over a
    discovered set, so the target names an entrypoint of every role that owns
    a file under that path, not of one known role.
    """
    for path_str in iter_project_files(extensions=(".yml", ".yaml")):
        path = Path(path_str)
        if "roles" not in path.parts and "tasks" not in path.parts:
            continue
        document = load_yaml_any(path_str, default_if_missing=None)
        if not isinstance(document, list):
            continue
        for task in _walk_tasks(document):
            args = _include_role_args(task)
            if not args:
                continue
            role = args.get("name")
            target = args.get("tasks_from")
            if not isinstance(role, str) or not isinstance(target, str):
                continue
            role, target = role.strip(), target.strip()
            if "{{" in target:
                continue
            yield path, None if "{{" in role else role, target


def _line_of(path: Path, needle: str) -> tuple[list[str], int]:
    lines = read_text(str(path)).splitlines()
    number = next((i for i, raw in enumerate(lines, 1) if needle in raw), 1)
    return lines, number


def unresolved_targets() -> list[str]:
    """Return one finding per include_role naming a tasks_from that is absent."""
    findings: list[str] = []
    for path, role, target in _iter_entrypoints():
        if role is None:
            continue
        candidate = PROJECT_ROOT / "roles" / role / "tasks" / target
        if not candidate.suffix:
            candidate = candidate.with_suffix(".yml")
        if candidate.is_file():
            continue
        lines, number = _line_of(path, f"tasks_from: {target}")
        if is_suppressed_at(lines, number, _RULE):
            continue
        findings.append(
            f"{path.relative_to(PROJECT_ROOT)}:{number}: role {role!r} has no "
            f"tasks/{target}"
        )
    return findings


def _include_tasks_target(task: dict) -> str | None:
    for key in _INCLUDE_TASKS_KEYS:
        args = task.get(key)
        if isinstance(args, str):
            return args.strip()
        if isinstance(args, dict) and isinstance(args.get("file"), str):
            return args["file"].strip()
    return None


def _nested_findings_for(role: str, entrypoint: str) -> list[str]:
    role_tasks = PROJECT_ROOT / "roles" / role / "tasks"
    findings: list[str] = []
    pending, seen = [role_tasks / entrypoint], set()
    while pending:
        current = pending.pop()
        if current in seen or not current.is_file():
            continue
        seen.add(current)
        document = load_yaml_any(str(current), default_if_missing=None)
        if not isinstance(document, list):
            continue
        for task in _walk_tasks(document):
            target = _include_tasks_target(task)
            if not target or "{{" in target:
                continue
            resolved = role_tasks / target
            if resolved.is_file():
                pending.append(resolved)
                continue
            if not (current.parent / target).is_file():
                continue
            lines, number = _line_of(current, target)
            if is_suppressed_at(lines, number, _NESTED_RULE):
                continue
            findings.append(
                f"{current.relative_to(PROJECT_ROOT)}:{number}: {target!r} resolves "
                f"only next to this file, but {role!r} is entered through "
                f"tasks_from: {entrypoint}, which resolves against tasks/"
            )
    return findings


def _roles_owning(target: str) -> list[str]:
    return [
        role_dir.name
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir())
        if (role_dir / "tasks" / target).is_file()
    ]


def unresolved_nested_includes() -> list[str]:
    """Return one finding per include below a tasks_from entrypoint that moves."""
    findings: list[str] = []
    for _, role, target in _iter_entrypoints():
        for owner in [role] if role else _roles_owning(target):
            findings.extend(_nested_findings_for(owner, target))
    return sorted(set(findings))


class TestTasksFromResolves(unittest.TestCase):
    def test_every_tasks_from_target_exists(self) -> None:
        findings = unresolved_targets()
        self.assertEqual(
            [],
            findings,
            f"include_role targets that do not exist ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_every_nested_include_resolves_from_the_tasks_dir(self) -> None:
        findings = unresolved_nested_includes()
        self.assertEqual(
            [],
            findings,
            f"includes that break when reached through tasks_from ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )


if __name__ == "__main__":
    unittest.main()
