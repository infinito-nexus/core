from __future__ import annotations

import copy
import os
import unittest
from itertools import pairwise
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import ROLE
from ._spec_secrets_wiring import (
    SECRETS_DIR,
    STAGE_DIR,
    TEMPLATE_EXISTS,
    environment,
    render,
    render_argv,
    role_tasks,
    role_vars,
    run_argv,
)

ROOT_HELPERS = frozenset(
    {
        "spec_secrets.py",
        "spec_secrets_container.py",
        "spec_secrets_match.py",
        "spec_secrets_mask.py",
        "run_parallel.py",
        "services.yml",
    }
)
TASK_FILES = ("01_setup.yml", "01_setup/parallel.yml", "03_run_pass/spec_secrets.yml")
RUN_ONE = "02_run_one.yml"
STAGE_VARS = {
    "_playwright_stage_dir": STAGE_DIR,
    "_playwright_stage_tests_dir": f"{STAGE_DIR}/tests",
}
ARCHIVE = ROLE / "files" / "archive_playwright_reports.sh"
SLOT_LINES = ('cd "$reports_dir"', 'subdir="variant-${variant_index}/${pass}"')
REPORT_DIRS = (
    "_playwright_pass_reports_dir",
    "_playwright_reports_dir",
    "TEST_E2E_PLAYWRIGHT_REPORTS_BASE_DIR",
)
EMPTYING = {
    "name": "✅ Ensure the pass reports dir exists, emptied first",
    "ansible.builtin.file": {
        "path": "{{ _playwright_pass_reports_dir }}",
        "state": "{{ playwright_reports_state }}",
        "mode": "0755",
    },
    "loop": f"{{{{ (['absent'] if ({TEMPLATE_EXISTS} | bool) else []) + ['directory'] }}}}",
    "loop_control": {"loop_var": "playwright_reports_state"},
}


def resolved(text: str) -> str:
    """Render a role path through the role's own variables.

    Args:
        text: a template naming variables of ``vars/main.yml``.

    Returns:
        The path once no variable is left, after at most four rounds.
    """
    variables = role_vars()
    for _ in range(4):
        if "{{" not in text:
            break
        text = environment().from_string(text).render(**variables)
    return text


def mounted_sources(tasks: list[dict]) -> list[Path]:
    """List the host side of every ``-v`` a command task of the list starts.

    Args:
        tasks: parsed tasks, blocks included.

    Returns:
        Each mount source, rendered.
    """
    sources = []
    for task in tasks:
        sources += mounted_sources(task.get("block", []))
        argv = task.get("ansible.builtin.command", {}).get("argv")
        if isinstance(argv, list):
            sources += [
                Path(resolved(str(value)).split(":")[0])
                for flag, value in pairwise(argv)
                if flag == "-v"
            ]
    return sources


def tools_violations(tasks_by_file: dict[str, list[dict]]) -> list[str]:
    """Check that every helper that runs as root lands in the tools dir no container mounts.

    Args:
        tasks_by_file: the parsed task files of ``TASK_FILES``.

    Returns:
        One message per helper shipped elsewhere, a missing helper, a tools
        dir nested with the shared dir or a setup mount that holds it.
    """
    shared = Path(resolved("{{ TEST_E2E_PLAYWRIGHT_SHARED_DIR }}"))
    tools = Path(resolved("{{ TEST_E2E_PLAYWRIGHT_TOOLS_DIR }}"))
    problems = []
    if tools.is_relative_to(shared) or shared.is_relative_to(tools):
        problems.append("the tools dir and the shared dir nest")
    shipped = {}
    for tasks in tasks_by_file.values():
        for task in tasks:
            copied = task.get("ansible.builtin.copy") or {}
            name = Path(str(copied.get("src", ""))).name
            if name in ROOT_HELPERS:
                shipped[name] = Path(resolved(copied["dest"])).parent
    if set(shipped) != ROOT_HELPERS:
        problems.append(f"the role ships only {sorted(shipped)} of the root helpers")
    problems += [
        f"{name} lands in {where}, not the tools dir"
        for name, where in sorted(shipped.items())
        if where != tools
    ]
    problems += [
        f"the setup mounts {source}, which holds the tools dir"
        for source in mounted_sources(tasks_by_file["01_setup.yml"])
        if tools.is_relative_to(source)
    ]
    return problems


def mountpoint_violations(run_one: list[dict]) -> list[str]:
    """Check that the stage dir holds a mountpoint for every mount below ``/e2e``.

    Args:
        run_one: the parsed ``02_run_one.yml``.

    Returns:
        One message per nested mount of a run with spec secrets whose
        directory no task creates before the run, read-only ``/e2e`` leaving
        docker unable to add it.
    """
    argv = render_argv(run_argv(), True, SECRETS_DIR)
    nested = sorted(
        str(value).split(":")[1]
        for flag, value in pairwise(argv)
        if flag == "-v" and str(value).split(":")[1].startswith("/e2e/")
    )
    run_at = next(
        i
        for i, task in enumerate(run_one)
        if task.get("ansible.builtin.include_tasks") == "03_run_pass.yml"
    )
    created = set()
    for task in run_one[:run_at]:
        made = task.get("ansible.builtin.file") or {}
        if made.get("state") != "directory":
            continue
        loop_var = task.get("loop_control", {}).get("loop_var", "item")
        for item in task.get("loop", [""]):
            scope = {**STAGE_VARS, loop_var: render(str(item), **STAGE_VARS)}
            created.add(render(made["path"], **scope))
    problems = [] if nested else ["a run with spec secrets mounts nothing below /e2e"]
    return problems + [
        f"{target} has no mountpoint in the stage dir"
        for target in nested
        if f"{STAGE_DIR}{target.removeprefix('/e2e')}" not in created
    ]


def setup_tasks() -> dict[str, list[dict]]:
    """Parse a fresh copy of each task file of ``TASK_FILES``.

    Returns:
        The tasks by file.
    """
    return {name: copy.deepcopy(role_tasks(name)) for name in TASK_FILES}


def all_role_tasks() -> dict[str, list[dict]]:
    """Parse a fresh copy of every task file of the role.

    Returns:
        The tasks by path below the role's ``tasks`` dir.
    """
    tasks = str(ROLE / "tasks") + os.sep
    return {
        path.removeprefix(tasks): copy.deepcopy(role_tasks(path.removeprefix(tasks)))
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(tasks)
    }


def flat(tasks: list[dict]) -> list[dict]:
    """List tasks with the tasks of their blocks.

    Args:
        tasks: parsed tasks.

    Returns:
        Each task, then those of its ``block``, ``rescue`` and ``always``.
    """
    found = []
    for task in tasks:
        found.append(task)
        for part in ("block", "rescue", "always"):
            found += flat(task.get(part, []))
    return found


def slot_violations(tasks_by_file: dict[str, list[dict]]) -> list[str]:
    """Check that no task removes a reports dir that keeps the archived variant slots.

    Args:
        tasks_by_file: the parsed task files of the role.

    Returns:
        One message per task that sets a reports dir ``absent`` for a run
        with spec secrets or without, and one when the archive no longer
        keeps each run in ``variant-N/`` below the reports dir.
    """
    archive = read_text(str(ARCHIVE))
    problems = [
        f"the archive no longer runs {line}"
        for line in SLOT_LINES
        if line not in archive.splitlines()
    ]
    for name, tasks in sorted(tasks_by_file.items()):
        for task in flat(tasks):
            made = task.get("ansible.builtin.file") or {}
            path = str(made.get("path", ""))
            if not any(variable in path for variable in REPORT_DIRS):
                continue
            loop_var = task.get("loop_control", {}).get("loop_var", "item")
            for exists in (True, False):
                facts = {
                    "_playwright_secrets_template_stat": {"stat": {"exists": exists}}
                }
                items = task.get("loop", [None])
                items = render(items, **facts) if isinstance(items, str) else items
                states = {
                    render(str(made.get("state")), **{loop_var: i}) for i in items
                }
                if "absent" in states:
                    problems.append(f"{name} removes {path} and its variant-* slots")
    return problems


class TestSpecSecretsTools(unittest.TestCase):
    def test_every_root_helper_lands_in_the_unmounted_tools_dir(self) -> None:
        self.assertEqual(tools_violations(setup_tasks()), [])

    def test_every_nested_mount_has_its_mountpoint_in_the_stage_dir(self) -> None:
        self.assertEqual(mountpoint_violations(role_tasks(RUN_ONE)), [])

    def test_no_task_removes_a_reports_dir_with_its_variant_slots(self) -> None:
        self.assertEqual(slot_violations(all_role_tasks()), [])


class TestSpecSecretsToolsNegativeControls(unittest.TestCase):
    def test_a_helper_shipped_into_the_shared_dir_is_caught(self) -> None:
        tasks = setup_tasks()
        helper = next(
            task["ansible.builtin.copy"]
            for task in tasks["01_setup.yml"]
            if str(task.get("ansible.builtin.copy", {}).get("src", "")).endswith(
                "/spec_secrets.py"
            )
        )
        helper["dest"] = "{{ TEST_E2E_PLAYWRIGHT_SHARED_DIR }}/spec_secrets.py"
        self.assertEqual(
            [problem.split(" lands")[0] for problem in tools_violations(tasks)],
            ["spec_secrets.py"],
        )

    def test_an_install_that_mounts_the_stage_base_is_caught(self) -> None:
        tasks = setup_tasks()
        text = str(tasks["01_setup.yml"])
        self.assertEqual(text.count("{{ TEST_E2E_PLAYWRIGHT_SHARED_DIR }}:/shared"), 1)
        install = next(t for t in tasks["01_setup.yml"] if "block" in t)["block"][0]
        argv = install["ansible.builtin.command"]["argv"]
        at = argv.index("{{ TEST_E2E_PLAYWRIGHT_SHARED_DIR }}:/shared")
        argv[at] = "{{ TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR }}:/shared"
        self.assertEqual(len(tools_violations(tasks)), 1)

    def test_a_stage_without_the_mountpoints_is_caught(self) -> None:
        run_one = [
            task
            for task in copy.deepcopy(role_tasks(RUN_ONE))
            if task.get("loop_control", {}).get("loop_var") != "playwright_mountpoint"
        ]
        self.assertEqual(
            mountpoint_violations(run_one),
            [
                "/e2e/node_modules has no mountpoint in the stage dir",
                "/e2e/tests/personas has no mountpoint in the stage dir",
            ],
        )

    def test_a_run_that_empties_the_reports_dir_is_caught(self) -> None:
        tasks = all_role_tasks()
        tasks["03_run_pass.yml"][0] = copy.deepcopy(EMPTYING)
        path = EMPTYING["ansible.builtin.file"]["path"]
        self.assertEqual(
            slot_violations(tasks),
            [f"03_run_pass.yml removes {path} and its variant-* slots"],
        )


if __name__ == "__main__":
    unittest.main()
