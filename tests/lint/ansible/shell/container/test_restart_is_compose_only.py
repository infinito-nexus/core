"""Enforce that a raw ``container restart`` can never run in swarm mode.

``restart`` stops and starts the same container. On a swarm task container
the stop phase disconnects it from the node-local overlay, swarmkit garbage
collects the sandbox because no task is left on that node, and the start
phase 171 ms later finds no network::

    network disconnect ik24tylon3tuoz4mz8bxutllw (container=56a0550133cd)
    network destroy    ik24tylon3tuoz4mz8bxutllw
    network create     ik24tylon3tuoz4mz8bxutllw
    Error response from daemon: Cannot restart container 56a0550133cd:
    failed to set up container networking: network ... not found

Swarmkit then schedules a replacement task that attaches cleanly, so the
stack heals itself and only the play fails. That is the expensive shape: a
red deploy over a healthy cluster, whose evidence is a millisecond-level
event race in a rescue bundle rather than anything the task reports.

The repository already knows the distinction and three shapes are accepted:

* the task carries ``IS_COMPOSE_MODE`` in its ``when:``, or sits in a block
  that does, with a separate swarm path beside it as ``web-app-odoo`` has;
* the command itself branches on the mode, as ``web-app-stalwart`` does,
  running ``container service update --force`` under swarm;
* the role drops the restart and notifies ``container-recreate`` instead,
  which ``sys-svc-compose`` implements per mode.

The sibling rules ``raw-docker`` and ``container-exec-resolver`` ask whether
docker is addressed directly, not which operation is sent, so a nocheck for
either of them does not answer this question.

Scope: ``roles/*/tasks/**/*.yml``. A restart written into a shell script
under ``files/`` or into a systemd unit runs outside a play, where no
handler exists, and is out of scope.

Suppress with ``# nocheck: container-restart-compose-only`` on the line or
directly above it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "container-restart-compose-only"
_RESTART = re.compile(r"\b(?:container|docker)\s+restart\b")
_MODE = re.compile(r"\bIS_(?:COMPOSE|SWARM)_MODE\b")
_COMMENT = re.compile(r"^\s*#")
_FAIL_KEYS = ("ansible.builtin.fail", "fail")
_INCLUDE_KEYS = (
    "ansible.builtin.include_tasks",
    "include_tasks",
    "ansible.builtin.import_tasks",
    "import_tasks",
)


def _is_scan_target(rel_path: str) -> bool:
    """Whether a repo-relative path is a role task file.

    Args:
        rel_path: path relative to the project root.
    """
    parts = rel_path.split("/")
    return len(parts) > 3 and parts[0] == "roles" and parts[2] == "tasks"


def _mapping_to_dict(node: yaml.MappingNode) -> dict[str, yaml.Node]:
    """Return a mapping node's children keyed by their scalar key.

    Args:
        node: the mapping node to flatten.
    """
    return {
        key.value: value
        for key, value in node.value
        if isinstance(key, yaml.ScalarNode)
    }


def _carries_mode(node: yaml.Node | None) -> bool:
    """Whether a ``when:`` node mentions a deployment-mode flag.

    Args:
        node: the ``when:`` node, or None.
    """
    if node is None:
        return False
    if isinstance(node, yaml.ScalarNode):
        return bool(_MODE.search(str(node.value)))
    if isinstance(node, yaml.SequenceNode):
        return any(_carries_mode(item) for item in node.value)
    return False


def _walk(node: yaml.Node, gated: bool, ranges: list[tuple[int, int]]) -> None:
    """Collect the line ranges of tasks a mode flag already guards.

    Args:
        node: the node to walk.
        gated: whether an enclosing block carries the flag.
        ranges: accumulator of (first line, last line) pairs.
    """
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _walk(item, gated, ranges)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    children = _mapping_to_dict(node)
    here = gated or _carries_mode(children.get("when"))
    if here:
        ranges.append((node.start_mark.line + 1, node.end_mark.line + 1))
    for key in ("block", "rescue", "always"):
        sub = children.get(key)
        if isinstance(sub, yaml.SequenceNode):
            _walk(sub, here, ranges)


def _gated_ranges(content: str) -> list[tuple[int, int]]:
    """Return the line ranges of mode-guarded tasks in a task file.

    Args:
        content: the file's text.
    """
    try:
        documents = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    ranges: list[tuple[int, int]] = []
    for document in documents:
        _walk(document, False, ranges)
    return ranges


def _argv_restart_lines(node: yaml.Node, lines: list[int]) -> None:
    """Collect the lines of restarts written as an ``argv`` list.

    The line form ``container restart X`` is one token stream, so a regex
    reads it; ``argv`` puts the verb on its own list item, which web-app-gitea
    does, and no line carries both words.

    Args:
        node: the node to walk.
        lines: accumulator of line numbers.
    """
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _argv_restart_lines(item, lines)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    for key, value in node.value:
        if isinstance(value, (yaml.MappingNode, yaml.SequenceNode)):
            _argv_restart_lines(value, lines)
        if not isinstance(key, yaml.ScalarNode) or key.value != "argv":
            continue
        if not isinstance(value, yaml.SequenceNode):
            continue
        words = [
            item.value for item in value.value if isinstance(item, yaml.ScalarNode)
        ]
        if (
            len(words) >= 2
            and words[0] in {"container", "docker"}
            and words[1] == "restart"
        ):
            lines.append(key.start_mark.line + 1)


def _include_is_compose_only(tasks: list, target: str) -> bool:
    """Whether every include of *target* in this task list is compose-only.

    An include site counts as compose-only when it carries IS_COMPOSE_MODE
    itself, or when an earlier sibling aborts the host under swarm, which is
    how svc-ai-lmstudio keeps its recovery path off a swarm node.

    Args:
        tasks: one task list of the including file.
        target: the included file's basename.
    """
    swarm_aborted = False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        when = str(task.get("when", ""))
        if any(key in task for key in _FAIL_KEYS) and "IS_SWARM_MODE" in when:
            swarm_aborted = True
        for key in ("block", "rescue", "always"):
            sub = task.get(key)
            if isinstance(sub, list) and _include_is_compose_only(sub, target):
                return True
        included = next((str(task[key]) for key in _INCLUDE_KEYS if key in task), None)
        if included and included.rstrip().endswith(target):
            return swarm_aborted or "IS_COMPOSE_MODE" in when
    return False


def _caller_gates_file(path: Path) -> bool:
    """Whether a sibling task file includes *path* on a compose-only site.

    Args:
        path: the included task file.
    """
    role = next((p for p in path.parents if p.parent.name == "roles"), None)
    if role is None:
        return False
    prefix = f"{role / 'tasks'}/"
    for other in iter_project_files(extensions=(".yml",)):
        if other == str(path) or not other.startswith(prefix):
            continue
        try:
            tasks = load_yaml_any(other)
        except yaml.YAMLError:
            continue
        if isinstance(tasks, list) and _include_is_compose_only(tasks, path.name):
            return True
    return False


def _offenders(rel_path: str, content: str) -> list[str]:
    """Return the ungated raw restarts of one task file.

    Args:
        rel_path: path relative to the project root.
        content: the file's text.
    """
    lines = content.splitlines()
    ranges = _gated_ranges(content)
    hits: list[int] = []
    for index, line in enumerate(lines, start=1):
        if not _RESTART.search(line) or _COMMENT.match(line):
            continue
        if _MODE.search(line):
            continue
        hits.append(index)
    try:
        for document in yaml.compose_all(content, Loader=yaml.SafeLoader):
            _argv_restart_lines(document, hits)
    except yaml.YAMLError:
        pass

    found: list[str] = []
    for index in sorted(set(hits)):
        if any(start <= index <= end for start, end in ranges):
            continue
        if is_suppressed_at(lines, index, _RULE, mode="same-or-above"):
            continue
        found.append(f"{rel_path}:{index}")
    return found


class TestContainerRestartIsComposeOnly(unittest.TestCase):
    def test_a_raw_restart_never_reaches_swarm(self) -> None:
        offenders: list[str] = []
        for path in iter_project_files(extensions=(".yml",)):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            if not _is_scan_target(rel):
                continue
            try:
                content = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if "restart" not in content:
                continue
            if _caller_gates_file(Path(path)):
                continue
            offenders.extend(_offenders(rel, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} raw container restart(s) can run in swarm mode, "
            "where the stop phase races swarmkit's overlay collection and the "
            "start phase fails with 'network ... not found':\n"
            f"{report}\n\n"
            "Gate the task on IS_COMPOSE_MODE and give swarm its own path, "
            "branch on the mode inside the command as web-app-stalwart does, "
            "or drop the restart and notify container-recreate.\n"
            f"Suppress a genuine exception with `# nocheck: {_RULE}`.",
        )


class TestGateDetection(unittest.TestCase):
    MODE_GATED = (
        "- name: restart it\n"
        "  ansible.builtin.command: container restart x\n"
        "  when: IS_COMPOSE_MODE\n"
    )
    BLOCK_GATED = (
        "- name: compose only\n"
        "  when: IS_COMPOSE_MODE\n"
        "  block:\n"
        "    - name: restart it\n"
        "      ansible.builtin.command: container restart x\n"
    )
    INLINE_BRANCH = (
        "- name: restart it\n"
        "  ansible.builtin.shell:\n"
        "    cmd: >-\n"
        "      {{ ('container restart ' ~ C) if IS_COMPOSE_MODE\n"
        "      else ('container service update --force ' ~ S) }}\n"
    )
    UNGATED = "- name: restart it\n  ansible.builtin.command: container restart x\n"

    def test_a_when_gate_on_the_task_is_accepted(self) -> None:
        self.assertEqual([], _offenders("roles/x/tasks/main.yml", self.MODE_GATED))

    def test_a_when_gate_on_an_enclosing_block_is_accepted(self) -> None:
        self.assertEqual([], _offenders("roles/x/tasks/main.yml", self.BLOCK_GATED))

    def test_a_branch_inside_the_command_is_accepted(self) -> None:
        self.assertEqual([], _offenders("roles/x/tasks/main.yml", self.INLINE_BRANCH))

    def test_an_ungated_restart_is_reported(self) -> None:
        self.assertEqual(
            ["roles/x/tasks/main.yml:2"],
            _offenders("roles/x/tasks/main.yml", self.UNGATED),
        )

    ARGV_UNGATED = (
        "- name: restart it\n"
        "  ansible.builtin.command:\n"
        "    argv:\n"
        "      - container\n"
        "      - restart\n"
        "      - x\n"
    )
    ARGV_GATED = ARGV_UNGATED + "  when: IS_COMPOSE_MODE\n"

    def test_an_argv_restart_is_reported(self) -> None:
        self.assertEqual(
            ["roles/x/tasks/main.yml:3"],
            _offenders("roles/x/tasks/main.yml", self.ARGV_UNGATED),
        )

    def test_a_gated_argv_restart_is_accepted(self) -> None:
        self.assertEqual([], _offenders("roles/x/tasks/main.yml", self.ARGV_GATED))

    def test_a_swarm_abort_before_the_include_gates_the_file(self) -> None:
        caller = [
            {
                "name": "preload",
                "block": [{"name": "pull", "include_tasks": "utils/preload/pull.yml"}],
                "rescue": [
                    {
                        "name": "re-raise in swarm",
                        "ansible.builtin.fail": {"msg": "failed"},
                        "when": "IS_SWARM_MODE",
                    },
                    {
                        "name": "recover",
                        "ansible.builtin.include_tasks": "utils/preload/recover.yml",
                    },
                ],
            }
        ]

        self.assertTrue(_include_is_compose_only(caller, "recover.yml"))

    def test_an_include_without_a_gate_does_not_count(self) -> None:
        caller = [{"name": "recover", "include_tasks": "utils/preload/recover.yml"}]

        self.assertFalse(_include_is_compose_only(caller, "recover.yml"))

    def test_a_nocheck_suppresses_it(self) -> None:
        suppressed = self.UNGATED.replace(
            "container restart x", f"container restart x # nocheck: {_RULE} reason"
        )
        self.assertEqual([], _offenders("roles/x/tasks/main.yml", suppressed))


if __name__ == "__main__":
    unittest.main()
