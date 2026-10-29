"""Lint: a role installs only the package ids the deploy-start batch leaves out.

The constructor installs every id of every role a deploy may run in one
``package_install`` run (``lookup('package_batch')``). An id stays out of it
only when its ``meta/packages.yml`` entry says ``batch: false``, and then the
role's own task installs it. Four rules hold that split together:

* an unconditional ``package_install`` task installs only ``batch: false``
  ids; any other id is covered by the batch, so the task goes;
* a ``package_install`` task under a ``when:``, on the task or an enclosing
  block, installs only ``batch: false`` ids, so the batch does not install
  them on hosts where the condition is false;
* every id of a role the constructor runs ahead of the batch is
  ``batch: false``, because the batch would install it too late;
* a role file references only ids the shared root file declares;
* every ``package_install`` task of a role carries
  ``# nocheck: package-install <reason>`` on its module line or the line
  above, naming why it cannot ride the batch. The batch cannot see the
  conditions an include or a role invocation puts around a task file, so an
  unmarked install would slip past the first two rules.

A ``run_once_<role>`` guard is no condition here: it only keeps a role from
running twice in one deploy.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.packages.registry import build_registry, load_references
from utils.roles.invocations import (
    CONSTRUCTOR_STAGE,
    NESTED_KEYS,
    STAGES_DIR,
    expand_roles,
    iter_tasks,
    role_names,
    task_invocations,
)

from . import PROJECT_ROOT

_RUN_ONCE_GUARD_RE = re.compile(
    r"^(?:run_once_\w+\s+is\s+not\s+defined"
    r"|not\s+\(\s*run_once_\w+\s*\|\s*default\(false\)\s*\|\s*bool\s*\))$"
)
_BATCH_LOOKUP = "lookup('package_batch'"
_RULE = "package-install"
_MODULE_LINE_RE = re.compile(r"^\s*(?:-\s+)?package_install:")


def _conditions(task: dict[str, Any]) -> list[str]:
    when = task.get("when")
    if when is None:
        return []
    return [
        str(condition).strip()
        for condition in (when if isinstance(when, list) else [when])
        if not _RUN_ONCE_GUARD_RE.match(str(condition).strip())
    ]


def _package_tasks(
    node: Any, inherited: list[str]
) -> list[tuple[dict[str, Any], list[str]]]:
    found: list[tuple[dict[str, Any], list[str]]] = []
    if not isinstance(node, list):
        return found
    for task in node:
        if not isinstance(task, dict):
            continue
        conditions = inherited + _conditions(task)
        if isinstance(task.get("package_install"), dict):
            found.append((task, conditions))
        for key in NESTED_KEYS:
            found.extend(_package_tasks(task.get(key), conditions))
    return found


def _ids(task: dict[str, Any]) -> list[str]:
    raw = task["package_install"].get("id")
    ids = raw if isinstance(raw, list) else [raw]
    return [str(item).strip() for item in ids if isinstance(item, str)]


def _role_task_files() -> list[Path]:
    roles = PROJECT_ROOT / "roles"
    return [
        Path(path)
        for path in iter_project_files(extensions=(".yml",))
        if Path(path).is_relative_to(roles)
        and Path(path).relative_to(roles).parts[1:2] in (("tasks",), ("handlers",))
    ]


def _constructor_tasks_ahead_of_the_batch() -> list[dict[str, Any]] | None:
    tasks = load_yaml_any(str(PROJECT_ROOT / STAGES_DIR / CONSTRUCTOR_STAGE))
    for index, task in enumerate(tasks):
        if "package_install" in task and _BATCH_LOOKUP in str(task.get("vars")):
            return tasks[:index]
    return None


def _roles_ahead_of_the_batch(tasks: list[dict[str, Any]]) -> set[str]:
    known = role_names(str(PROJECT_ROOT / "roles"))
    seeds: set[str] = set()
    for task in iter_tasks(tasks):
        seeds |= task_invocations(task, known)[0]
    return expand_roles({}, seeds, project_root=PROJECT_ROOT)


class TestPackageBatch(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_registry(PROJECT_ROOT)

    def _offenders(self, *, conditional: bool) -> list[str]:
        offenders: list[str] = []
        for path in _role_task_files():
            doc = load_yaml_any(str(path), default_if_missing=None)
            for task, conditions in _package_tasks(doc, []):
                if bool(conditions) != conditional:
                    continue
                batched = [
                    package_id
                    for package_id in _ids(task)
                    if package_id in self.registry and self.registry[package_id].batch
                ]
                if batched:
                    rel = path.relative_to(PROJECT_ROOT)
                    offenders.append(
                        f"{rel}: '{task.get('name', 'unnamed')}' installs "
                        f"{', '.join(batched)}"
                    )
        return offenders

    def test_unconditional_tasks_install_only_unbatched_ids(self) -> None:
        offenders = self._offenders(conditional=False)
        if offenders:
            self.fail(
                f"{len(offenders)} unconditional package_install task(s) install an "
                "id the deploy-start batch already installs. Remove the task, or "
                "flag the id 'batch: false' in its meta/packages.yml when it must "
                "wait for a setup step the role runs first:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_conditional_tasks_install_only_unbatched_ids(self) -> None:
        offenders = self._offenders(conditional=True)
        if offenders:
            self.fail(
                f"{len(offenders)} package_install task(s) under a when: install an "
                "id the deploy-start batch installs unconditionally. Flag the id "
                "'batch: false' in its meta/packages.yml:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_roles_ahead_of_the_batch_install_only_unbatched_ids(self) -> None:
        tasks = _constructor_tasks_ahead_of_the_batch()
        self.assertIsNotNone(
            tasks,
            f"{STAGES_DIR / CONSTRUCTOR_STAGE} has no package_install task fed by "
            f"{_BATCH_LOOKUP}...), so no deploy installs the batched ids.",
        )
        references = load_references(PROJECT_ROOT)
        offenders: list[str] = []
        for role in sorted(_roles_ahead_of_the_batch(tasks)):
            owned = {
                package_id
                for package_id, declaration in self.registry.items()
                if declaration.role == role
            }
            for package_id in sorted(owned | references.get(role, set())):
                declaration = self.registry.get(package_id)
                if declaration is not None and declaration.batch:
                    offenders.append(f"{role}: {package_id}")
        if offenders:
            self.fail(
                f"{len(offenders)} id(s) belong to a role the constructor runs before "
                "the deploy-start batch, so the batch installs them too late. Flag "
                "each 'batch: false' in its meta/packages.yml:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_role_package_installs_are_marked(self) -> None:
        offenders: list[str] = []
        for path in _role_task_files():
            lines = read_text(str(path)).splitlines()
            offenders.extend(
                f"{path.relative_to(PROJECT_ROOT)}:{number}"
                for number, line in enumerate(lines, start=1)
                if _MODULE_LINE_RE.match(line)
                and not is_suppressed_at(lines, number, _RULE)
            )
        if offenders:
            self.fail(
                f"{len(offenders)} package_install task(s) in a role bypass the "
                "deploy-start batch without saying why. Drop the task so the batch "
                "installs the id, or flag the id 'batch: false' and mark the task "
                f"'# nocheck: {_RULE} <why it cannot ride the batch>':\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_references_name_shared_ids(self) -> None:
        offenders = [
            f"roles/{role}/meta/packages.yml: '{package_id}'"
            for role, package_ids in sorted(load_references(PROJECT_ROOT).items())
            for package_id in sorted(package_ids)
            if package_id not in self.registry or not self.registry[package_id].shared
        ]
        if offenders:
            self.fail(
                f"{len(offenders)} 'shared: true' reference(s) name no id of the "
                "root meta/packages.yml:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
