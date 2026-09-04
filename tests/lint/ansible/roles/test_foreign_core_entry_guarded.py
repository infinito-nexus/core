"""A role that enters another role's numbered core must carry its run-once guard.

Rationale
=========
``roles/<role>/tasks/main.yml`` gates ``0N_core.yml`` behind
``run_once_<role> is not defined``. Reaching that body from a *different* role
with ``include_role: {name: <role>, tasks_from: 0N_core.yml}`` bypasses the
gate, because the guard lives in ``main.yml`` and ``tasks_from`` never reads it.
The body then re-runs once per calling task rather than once per play.

That is not merely wasteful. ``roles/sys-svc-compose/tasks/00_core.yml`` removes
the shared compose pull-lock directory, which ``files/python/pull.py`` uses to
skip a pull it already did, so a second pass makes every stack deployed so far
pull again; and under ``MODE_RESET`` it reaches ``01_reset.yml``, which brings
every project in ``DIR_COMPOSITIONS`` down and deletes the directory that holds
every application's instance, env and volume paths.
``roles/sys-svc-container/tasks/00_core.yml`` carries an unconditional
``meta: flush_handlers``, so a second pass drains whatever topic is pending.

The guard belongs at the call site rather than inside the core file, because
``roles/sys-svc-compose/tasks/00_core.yml`` sets its own flag as the first task
to break the recursion back through ``utils/network/routine.yml``. Seven call
sites already guard ``sys-svc-container`` this way; this rule holds the rest to
the same convention.

``tests/lint/ansible/roles/test_service_core_first_task_run_once.py`` pins the
guard inside the owning role and cannot see a foreign entry point;
``tests/lint/ansible/tasks/test_tasks_from_resolves.py`` only checks that the
referenced file exists.

Per-line opt-out
================
Add ``# nocheck: foreign-core-entry-guarded`` on the ``tasks_from`` line or the
one above it, together with a comment naming why the body has to run again.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

_RULE = "foreign-core-entry-guarded"

_CORE_FILE = re.compile(r"^\d+_core(\.yml)?$")
_CORE_LINE = re.compile(r"^\s*tasks_from\s*:\s*['\"]?\d+_core(\.yml)?['\"]?\s*(?:#.*)?$")


def _owning_role(rel_path: str) -> str:
    parts = Path(rel_path).parts
    return parts[1] if len(parts) > 2 and parts[0] == "roles" else ""


def _guard_for(role: str) -> str:
    return f"run_once_{role.replace('-', '_')} is not defined"


def _role_include(task: Mapping) -> Mapping:
    for key in ("include_role", "import_role"):
        include = task.get(key) or task.get(f"ansible.builtin.{key}")
        if isinstance(include, Mapping):
            return include
    return {}


def _walk(tasks: object):
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        yield task
        for section in ("block", "rescue", "always"):
            yield from _walk(task.get(section))


def _core_entries(content: str) -> list[tuple[str, bool, str]]:
    """Return (target role, guarded, task name) for every foreign core entry."""
    try:
        tasks = load_yaml_str(content)
    except Exception:
        return []
    found: list[tuple[str, bool, str]] = []
    for task in _walk(tasks):
        include = _role_include(task)
        target = str(include.get("name") or "").strip()
        tasks_from = str(include.get("tasks_from") or "").strip()
        if not target or not _CORE_FILE.match(tasks_from):
            continue
        when = task.get("when")
        clauses = when if isinstance(when, list) else [when]
        guarded = any(_guard_for(target) in str(c) for c in clauses if c is not None)
        found.append((target, guarded, str(task.get("name") or tasks_from)))
    return found


class TestForeignCoreEntryGuarded(unittest.TestCase):
    def test_a_foreign_core_entry_carries_the_owning_role_guard(self) -> None:
        findings: list[tuple[str, int, str, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if "/tasks/" not in rel and not rel.startswith("tasks/"):
                continue
            entries = _core_entries(content)
            if not entries:
                continue
            lines = content.splitlines()
            anchors = [i for i, line in enumerate(lines) if _CORE_LINE.match(line)]
            if len(anchors) != len(entries):
                anchors = [0] * len(entries)
            owner = _owning_role(rel)
            for (target, guarded, name), idx in zip(entries, anchors):
                if guarded or target == owner:
                    continue
                if idx and is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, name, _guard_for(target)))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {t!r} needs `when: {g}`"
                for p, n, t, g in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "A role reaches another role's numbered core body through "
                "`tasks_from` without the guard that `main.yml` would have "
                "applied. The body then runs once per calling task instead of "
                "once per play, which re-runs installs, wipes the shared "
                "compose pull-lock directory, and under MODE_RESET tears down "
                "DIR_COMPOSITIONS after other applications are already "
                "deployed into it.\n\n"
                "Default: add the `when:` shown. Use the nocheck only where "
                "the body genuinely has to repeat, and say why.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
