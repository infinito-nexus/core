from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles" / "web-app-openpost" / "tasks"
PRODUCER = "netns.yml"
GATE = "IS_STACK_HOST | bool"
INCLUDES = ("include_tasks", "ansible.builtin.include_tasks")
SECTIONS = ("block", "rescue", "always")
READ = re.compile(r"\bOPENPOST_(NETNS_PYTHON|NETNS_ENTER|HOST_NODE|LOCAL_CID)\b")
PRODUCES = re.compile(
    r"(resolve_output_prefix|netns_output_prefix):\s*OPENPOST\s*$", re.MULTILINE
)


def _task_files() -> dict[str, str]:
    files = {}
    for name in iter_project_files(extensions=(".yml",), exclude_tests=True):
        path = Path(name)
        if path.is_relative_to(TASKS):
            files[path.relative_to(TASKS).as_posix()] = read_text(name)
    return files


def _when(task: dict) -> list[str]:
    value = task.get("when")
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value else []


def _target(task: dict) -> str | None:
    for key in INCLUDES:
        value = task.get(key)
        value = value.get("file") if isinstance(value, dict) else value
        if isinstance(value, str) and "{{" not in value:
            return value
    return None


def _reached(
    tasks, gates: tuple[str, ...], seen: dict[str, set[tuple[str, ...]]]
) -> None:
    """Args:
    tasks: a parsed tasks list of the role.
    gates: the when conditions every task of ``tasks`` runs under.
    seen: role task file to the gate sets it is reached under; filled in place.
    """
    for task in tasks if isinstance(tasks, list) else []:
        if not isinstance(task, dict):
            continue
        own = gates + tuple(_when(task))
        target = _target(task)
        if target is not None and own not in seen.setdefault(target, set()):
            seen[target].add(own)
            _reached(
                load_yaml_any(str(TASKS / target), default_if_missing=[]), own, seen
            )
        for section in SECTIONS:
            _reached(task.get(section), own, seen)


def _unproduced_readers(core: list) -> list[str]:
    """Args:
        core: the parsed task list of tasks/00_core.yml.

    Returns:
        Every role task file that reads an OPENPOST netns fact on some path that
        does not run the producer first under the same gate.
    """
    produced = [
        index
        for index, task in enumerate(core)
        if _target(task) == PRODUCER and _when(task) == [GATE]
    ]
    before: dict[str, set[tuple[str, ...]]] = {}
    after: dict[str, set[tuple[str, ...]]] = {}
    split = produced[0] if produced else len(core)
    _reached(core[:split], (), before)
    _reached(core[split + 1 :] if produced else [], (), after)
    readers = {
        name
        for name, text in _task_files().items()
        if READ.search(text) and name != PRODUCER
    }
    return sorted(
        name
        for name in readers
        if name in before
        or name not in after
        or any(GATE not in gates for gates in after[name])
    )


class TestOpenPostNetnsProducer(unittest.TestCase):
    def test_one_file_produces_the_openpost_netns_facts(self) -> None:
        self.assertEqual(
            [PRODUCER],
            sorted(
                name for name, text in _task_files().items() if PRODUCES.search(text)
            ),
        )

    def test_every_reader_runs_after_the_producer_under_its_gate(self) -> None:
        core = load_yaml_any(str(TASKS / "00_core.yml"), default_if_missing=[])
        self.assertEqual([], _unproduced_readers(core))

    def test_negative_control_without_the_producer_every_reader_is_flagged(
        self,
    ) -> None:
        core = load_yaml_any(str(TASKS / "00_core.yml"), default_if_missing=[])
        stripped = [task for task in core if _target(task) != PRODUCER]
        self.assertIn("03_breakglass.yml", _unproduced_readers(stripped))
        self.assertIn("crossposter/provision.yml", _unproduced_readers(stripped))


if __name__ == "__main__":
    unittest.main()
