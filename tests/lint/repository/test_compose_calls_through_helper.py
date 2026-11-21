"""Lint: every ``docker compose`` call reaches the dev stack through one helper.

The helper passes ``-p`` and the ``-f`` list, so ``INFINITO_STACK_NAME``
addresses every call and no call falls back to an implicit project.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

SCOPES = ("cli/", "scripts/", "utils/")
HELPERS = frozenset(
    {
        "cli/administration/deploy/development/stack.py",
        "scripts/meta/compose.sh",
    }
)
FOREIGN_STACKS = {
    "scripts/container/purge/web.sh": "a role stack under /opt/compose inside the container",
    "scripts/container/purge/entity/compose.sh": "a role stack under /opt/compose inside the container",
    "scripts/tests/deploy/swarm/routine/01_bootstrap.sh": "the swarm lab, with its own -p",
}
_SHELL_CALL = re.compile(r"\bdocker\s+compose\b")
_PYTHON_CALL = re.compile(r"""["']docker["']\s*,\s*["']compose["']""")


def compose_calls(relative: str, text: str) -> list[int]:
    """Args:
        relative: repository-relative path, which selects the language.
        text: file content.

    Returns:
        The line numbers of raw ``docker compose`` calls.
    """
    if relative.endswith(".py"):
        return [text.count("\n", 0, m.start()) + 1 for m in _PYTHON_CALL.finditer(text)]
    return [
        number
        for number, line in enumerate(text.splitlines(), 1)
        if not line.lstrip().startswith("#") and _SHELL_CALL.search(line)
    ]


def findings(root: Path) -> list[str]:
    """Args:
        root: repository root.

    Returns:
        ``path:line`` for every raw call outside the helpers and foreign stacks.
    """
    out: list[str] = []
    for path in iter_project_files(extensions=(".py", ".sh")):
        relative = Path(path).relative_to(root).as_posix()
        if not relative.startswith(SCOPES):
            continue
        if relative in HELPERS or relative in FOREIGN_STACKS:
            continue
        out += [f"{relative}:{n}" for n in compose_calls(relative, read_text(path))]
    return out


class TestComposeCallsThroughHelper(unittest.TestCase):
    def test_no_raw_compose_call(self) -> None:
        self.assertEqual(
            findings(PROJECT_ROOT),
            [],
            "Call `infinito_compose` (scripts/meta/compose.sh) or "
            "compose_argv (cli/administration/deploy/development/stack.py).",
        )

    def test_the_exempt_files_still_exist(self) -> None:
        for relative in (*HELPERS, *FOREIGN_STACKS):
            self.assertTrue((PROJECT_ROOT / relative).is_file(), relative)

    def test_a_shell_call_is_found_and_a_comment_is_not(self) -> None:
        text = "# docker compose down\nif ! docker compose ps -q infinito; then\n"
        self.assertEqual(compose_calls("x.sh", text), [2])

    def test_a_python_argv_split_over_lines_is_found(self) -> None:
        text = 'x = 1\ncmd = [\n    "docker",\n    "compose",\n    "ps",\n]\n'
        self.assertEqual(compose_calls("x.py", text), [3])

    def test_prose_in_python_is_not_a_call(self) -> None:
        text = 'help="Show docker compose logs for the development stack."\n'
        self.assertEqual(compose_calls("x.py", text), [])


if __name__ == "__main__":
    unittest.main()
