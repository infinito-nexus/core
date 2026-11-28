from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT
from .test_stack_bridge import BRIDGE
from .test_stack_guard import _include, _label, _role, _target, _tasks, owning_role

STAGE = Path("tasks/utils/stack/stage.yml")
STAGE_NAME = "/".join(STAGE.parts[-2:])
ENTRY_BACK = "tasks/utils/load/entry/back.yml"
BRIDGE_FILE = str(BRIDGE.relative_to("tasks"))
NESTED = ("block", "rescue", "always")
ROLE_INCLUDES = (
    "include_role",
    "import_role",
    "ansible.builtin.include_role",
    "ansible.builtin.import_role",
)


def stages_without_a_bridge(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        the roles that ship a stack stage but no bridge, so nothing runs it.
    """
    return sorted(
        owning_role(path, STAGE).name
        for path in root.glob(f"roles/*/{STAGE}")
        if not (owning_role(path, STAGE) / BRIDGE).is_file()
    )


def _flat(tasks: list[dict]) -> list[dict]:
    found = []
    for task in tasks:
        found.append(task)
        for key in NESTED:
            found.extend(
                _flat([step for step in task.get(key) or [] if isinstance(step, dict)])
            )
    return found


def stage_files(root: Path, role: str) -> set[Path]:
    """Args:
        root: the repository root.
        role: a role name.

    Returns:
        the role's stack stage and every task file of that role it reaches
        through blocks and includes.
    """
    role_dir = root / "roles" / role
    queue = [role_dir / STAGE] if (role_dir / STAGE).is_file() else []
    seen: set[Path] = set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        for task in _flat(_tasks(path)):
            target = _target(root, role_dir, _include(task))
            if target and target.is_file() and role_dir in target.parents:
                queue.append(target)
    return seen


def _owner(root: Path, path: Path, fallback: Path) -> Path:
    roles = root / "roles"
    return (
        roles / path.relative_to(roles).parts[0] if roles in path.parents else fallback
    )


def _reentries(root: Path, role_dir: Path, tasks: list[dict], seen: set) -> list[str]:
    found = []
    for task in tasks:
        for key in NESTED:
            nested = [step for step in task.get(key) or [] if isinstance(step, dict)]
            found.extend(_reentries(root, role_dir, nested, seen))
        for key in ROLE_INCLUDES:
            spec = task.get(key)
            if isinstance(spec, dict) and (
                spec.get("name") == "svc-stack"
                or BRIDGE_FILE in str(spec.get("tasks_from", ""))
            ):
                found.append(_label(task))
        include = _include(task)
        if BRIDGE_FILE in include:
            found.append(_label(task))
            continue
        target = _target(root, role_dir, include)
        if target and target.is_file() and target not in seen:
            seen.add(target)
            owner = _owner(root, target, role_dir)
            found.extend(_reentries(root, owner, _tasks(target), seen))
    return found


def stage_reentries(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        ``role: task`` for every task a stack stage runs, through blocks and
        includes, that reaches a bridge or svc-stack again.
    """
    found = []
    for path in sorted(root.glob(f"roles/*/{STAGE}")):
        role_dir = owning_role(path, STAGE)
        found.extend(
            f"{role_dir.name}: {label}"
            for label in _reentries(root, role_dir, _tasks(path), {path})
        )
    return found


def stage_callers(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        every task file besides the entry helper that names a stack stage.
    """
    files = [*root.glob("tasks/**/*.yml"), *root.glob("roles/*/tasks/**/*.yml")]
    return sorted(
        str(path.relative_to(root))
        for path in files
        if str(path.relative_to(root)) != ENTRY_BACK
        and STAGE_NAME in read_text(str(path))
    )


STEP = "- ansible.builtin.debug:\n    msg: step\n"
BRIDGED = {str(BRIDGE): "---\n[]\n"}


class TestStackStage(unittest.TestCase):
    def test_every_stage_role_ships_the_bridge(self) -> None:
        self.assertEqual(stages_without_a_bridge(PROJECT_ROOT), [])

    def test_no_stage_reaches_the_bridge_again(self) -> None:
        self.assertEqual(
            stage_reentries(PROJECT_ROOT),
            [],
            f"the entry runs {STAGE} right before the backend: keep the bridge "
            "and svc-stack out of it",
        )

    def test_only_the_entry_runs_a_stage(self) -> None:
        self.assertEqual(
            stage_callers(PROJECT_ROOT),
            [],
            f"only {ENTRY_BACK} runs {STAGE}; the front batch runs guards only",
        )

    def test_a_stage_without_a_bridge_or_reaching_it_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _role(root, "web-app-loose", {str(STAGE): STEP})
            _role(root, "web-app-clean", {**BRIDGED, str(STAGE): STEP})
            _role(
                root,
                "web-app-looping",
                {**BRIDGED, str(STAGE): "- include_tasks: utils/stack.yml\n"},
            )
            _role(
                root,
                "web-app-nested",
                {
                    **BRIDGED,
                    str(STAGE): "- include_tasks: inner.yml\n",
                    "tasks/inner.yml": (
                        "- block:\n"
                        "    - name: reach svc-stack\n"
                        "      include_role:\n"
                        "        name: svc-stack\n"
                        "        tasks_from: consumer.yml\n"
                    ),
                },
            )
            self.assertEqual(stages_without_a_bridge(root), ["web-app-loose"])
            self.assertEqual(
                stage_reentries(root),
                [
                    "web-app-looping: utils/stack.yml",
                    "web-app-nested: reach svc-stack",
                ],
            )

    def test_the_stage_files_follow_blocks_and_includes_inside_the_role(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foreign = "roles/web-svc-other/tasks/step.yml"
            _role(root, "web-svc-other", {"tasks/step.yml": STEP})
            _role(
                root,
                "web-app-staged",
                {
                    **BRIDGED,
                    str(STAGE): (
                        "- block:\n"
                        "    - include_tasks: inner.yml\n"
                        "- include_tasks: \"{{ lookup('path_absolute', "
                        f"'{foreign}') }}}}\"\n"
                    ),
                    "tasks/inner.yml": "- include_tasks: deeper.yml\n",
                    "tasks/deeper.yml": STEP,
                    "tasks/00_core.yml": "- include_tasks: core_only.yml\n",
                    "tasks/core_only.yml": STEP,
                },
            )
            tasks = root / "roles/web-app-staged/tasks"
            self.assertEqual(
                stage_files(root, "web-app-staged"),
                {
                    tasks / "utils/stack/stage.yml",
                    tasks / "inner.yml",
                    tasks / "deeper.yml",
                },
            )
            self.assertEqual(stage_files(root, "web-svc-other"), set())

    def test_a_caller_besides_the_entry_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            naming = f"- include_tasks: {STAGE_NAME}\n"
            for rel in (ENTRY_BACK, "roles/svc-stack/tasks/batch/serve.yml"):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(naming, encoding="utf-8")
            self.assertEqual(
                stage_callers(root), ["roles/svc-stack/tasks/batch/serve.yml"]
            )


if __name__ == "__main__":
    unittest.main()
