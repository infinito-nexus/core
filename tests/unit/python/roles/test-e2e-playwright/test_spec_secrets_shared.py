from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT, ROLE
from ._spec_secrets_fakes import MASKER, install
from ._spec_secrets_wiring import holds, role_tasks

ORCHESTRATE = "01_setup/orchestrate.yml"
RERUN = PROJECT_ROOT / "scripts" / "tests" / "e2e" / "rerun-spec.sh"
ISOLATED = re.compile(r"""python3[\s'",-]+I[\s'",-]+B\b""")
OWNED_DIRS = [
    "{{ TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR }}",
    "{{ TEST_E2E_PLAYWRIGHT_SHARED_DIR }}",
    "{{ TEST_E2E_PLAYWRIGHT_TOOLS_DIR }}",
]
BASE_DIR = {
    "argv": ["mkdir", "-m", "0755", "{{ TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR }}"],
    "creates": "{{ TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR }}",
}
MAKERS = ("ansible.builtin.file", "ansible.builtin.command")
FILE_MODULE = {
    "ansible.builtin.file": {
        "path": "{{ TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR }}",
        "state": "directory",
        "follow": False,
        "mode": "0755",
    }
}
OWNED = {
    "exists": True,
    "isdir": True,
    "islnk": False,
    "uid": 0,
    "wgrp": False,
    "woth": False,
}
SQUATS = {
    "foreign owner": {"uid": 1000},
    "link": {"islnk": True},
    "file": {"isdir": False},
    "group writable": {"wgrp": True},
    "world writable": {"woth": True},
}
ROOT_ONLY = " and playwright_owned.stat.uid == 0"
SEARCH_PATH = "sys.path.append(str(Path(__file__).parent))\n"
SHADOW = (
    "import pathlib\n"
    "pathlib.Path(__file__).with_name('shadowed').touch()\n"
    "raise ImportError('planted')\n"
)


def squat_violations(tasks: list[dict]) -> list[str]:
    """Check that the run creates the stage base with mkdir, then refuses another user's dirs.

    Args:
        tasks: the parsed orchestrate task file.

    Returns:
        One message per broken expectation.
    """
    problems = []
    create, read, check = tasks[:3]
    if create.get("ansible.builtin.command") != BASE_DIR:
        problems.append("the stage base is not made by a mkdir that never follows")
    if any(maker in task for maker in MAKERS for task in (read, check)):
        return [*problems, "a dir is created between the read and the check"]
    stat = read.get("ansible.builtin.stat", {})
    if stat.get("follow") is not False or read.get("loop") != OWNED_DIRS:
        problems.append("the check does not read the dirs without following a link")
    if check.get("loop") != f"{{{{ {read.get('register')}.results }}}}":
        problems.append("the check does not hold what was read")
    conditions = check.get("ansible.builtin.assert", {}).get("that", [])
    for name, change in SQUATS.items():
        if holds(conditions, playwright_owned={"stat": {**OWNED, **change}}):
            problems.append(f"a {name} dir passes")
    problems.extend(
        f"a {fine} dir is refused"
        for fine in ({"exists": False}, OWNED)
        if not holds(conditions, playwright_owned={"stat": fine})
    )
    return problems


def helper_texts() -> dict[str, str]:
    """Read every file that starts a helper of the role with ``python3``.

    Returns:
        The text of each role task file, of ``vars/main.yml`` and of
        ``rerun-spec.sh`` by path.
    """
    tasks = str(ROLE / "tasks") + os.sep
    paths = [
        path
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(tasks)
    ]
    paths += [str(ROLE / "vars" / "main.yml"), str(RERUN)]
    return {path: read_text(path) for path in sorted(paths)}


def unisolated(texts: dict[str, str]) -> list[str]:
    """Name the files that start ``python3`` without ``-I -B``.

    Args:
        texts: file text by path.

    Returns:
        The paths where a ``python3`` lacks the two flags right behind it.
    """
    return [
        path
        for path, text in texts.items()
        if text.count("python3") != len(ISOLATED.findall(text))
    ]


def masker_start(*replacements: tuple[str, str], planted: bool = False) -> list:
    """Start the installed masker isolated, a stdlib module planted next to it.

    Args:
        *replacements: changes to the masker, for a negative control.
        planted: whether a ``json.py`` that marks its import sits in its dir.

    Returns:
        The exit code of a bad-usage call, whether its helpers were not
        found, whether the planted module ran and whether bytecode was
        written.
    """
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp) / "bin"
        install(bin_dir, Path(tmp), *replacements)
        if planted:
            (bin_dir / "json.py").write_text(SHADOW, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(bin_dir / MASKER.name), "usage"],
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp,
        )
        return [
            result.returncode,
            "ModuleNotFoundError" in result.stderr,
            (bin_dir / "shadowed").exists(),
            (bin_dir / "__pycache__").exists(),
        ]


class TestSpecSecretsShared(unittest.TestCase):
    def test_a_squatted_stage_base_shared_or_tools_dir_is_refused(self) -> None:
        self.assertEqual(squat_violations(role_tasks(ORCHESTRATE)), [])

    def test_every_helper_starts_isolated_without_bytecode(self) -> None:
        self.assertEqual(unisolated(helper_texts()), [])

    def test_the_isolated_masker_finds_its_helpers_but_no_planted_module(
        self,
    ) -> None:
        self.assertEqual(masker_start(), [2, False, False, False])
        self.assertEqual(masker_start(planted=True), [2, False, False, False])


class TestSpecSecretsSharedNegativeControls(unittest.TestCase):
    def test_a_check_that_accepts_another_owner_or_follows_a_link_is_caught(
        self,
    ) -> None:
        tasks = copy.deepcopy(role_tasks(ORCHESTRATE))
        that = tasks[2]["ansible.builtin.assert"]["that"]
        self.assertEqual(that[0].count(ROOT_ONLY), 1)
        that[0] = that[0].replace(ROOT_ONLY, "")
        self.assertIn("a foreign owner dir passes", squat_violations(tasks))
        tasks = copy.deepcopy(role_tasks(ORCHESTRATE))
        tasks[1]["ansible.builtin.stat"]["follow"] = True
        self.assertNotEqual(squat_violations(tasks), [])
        for name, task in {
            "file module": FILE_MODULE,
            "mkdir -p": {
                "ansible.builtin.command": {
                    **BASE_DIR,
                    "argv": ["mkdir", "-p", *BASE_DIR["argv"][1:]],
                }
            },
        }.items():
            with self.subTest(create=name):
                tasks = copy.deepcopy(role_tasks(ORCHESTRATE))
                tasks[0] = task
                self.assertEqual(
                    squat_violations(tasks),
                    ["the stage base is not made by a mkdir that never follows"],
                )
        tasks = copy.deepcopy(role_tasks(ORCHESTRATE))
        tasks.insert(2, tasks.pop(0))
        self.assertIn(
            "a dir is created between the read and the check", squat_violations(tasks)
        )

    def test_a_helper_started_without_isolation_is_caught(self) -> None:
        texts = helper_texts()
        vars_main = str(ROLE / "vars" / "main.yml")
        texts[vars_main] = texts[vars_main].replace("'-I', ", "", 1)
        self.assertEqual(unisolated(texts), [vars_main])

    def test_a_masker_that_misses_or_shadows_its_search_path_is_caught(
        self,
    ) -> None:
        self.assertEqual(masker_start((SEARCH_PATH, ""))[:2], [1, True])
        front = SEARCH_PATH.replace("append(", "insert(0, ")
        self.assertEqual(masker_start((SEARCH_PATH, front), planted=True)[2], True)


if __name__ == "__main__":
    unittest.main()
