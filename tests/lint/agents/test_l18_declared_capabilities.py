"""L18: environment differences are declared capabilities, never a branch on
the runtime identity. No role logic, skill or routine branches on
runs_on_github or a RUNTIME identity check."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from tests.lint.agents import AGENTS_DIR, PROJECT_ROOT
from utils.cache.files import iter_project_files_with_content, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

IDENTITY = re.compile(r"runs_on_github|\bRUNTIME\b\s*==|==\s*['\"]github['\"]")
ROLE_LOGIC = frozenset({"roles", "plugins", "group_vars"})
ROLE_LOGIC_SUFFIXES = (".yml", ".yaml", ".j2", ".py")


def identity_problems(files: Iterable[tuple[str, str]]) -> list[str]:
    """Return every line that branches on the runtime identity.

    Args:
        files: ``(relative path, text)`` pairs to scan.
    """
    return [
        f"{path}:{number}: runtime-identity branch"
        for path, text in files
        for number, line in enumerate(text.splitlines(), 1)
        if IDENTITY.search(line)
    ]


def check(agents_dir: Path) -> list[str]:
    return identity_problems(
        (str(path.relative_to(agents_dir)), read_text(str(path)))
        for path in sorted(agents_dir.rglob("*.py"))  # nocheck: project-walk
        if path.is_file()
    )


def role_logic_files() -> Iterator[tuple[str, str]]:
    for path, text in iter_project_files_with_content(extensions=ROLE_LOGIC_SUFFIXES):
        relative = Path(path).relative_to(PROJECT_ROOT)
        if relative.parts[0] in ROLE_LOGIC:
            yield str(relative), text


class TestL18(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_role_logic_passes(self):
        self.assertEqual(identity_problems(role_logic_files()), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                "if runs_on_github:\n    pass\n", encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])
        task = "- name: Skip on the hosted runner\n  when: RUNTIME == 'github'\n"
        self.assertNotEqual(
            identity_problems([(f"roles/x/{ROLE_FILE_TASKS_MAIN}", task)]), []
        )


if __name__ == "__main__":
    unittest.main()
