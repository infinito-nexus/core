"""Enforce that a constructed ``timeout`` argv passes ``--foreground``.

``timeout`` without it calls ``setpgid``, so the command it wraps leaves the
caller's process group. A wrapped command that then reads the controlling
terminal takes SIGTTIN and stops forever rather than being killed at the
deadline, which is the opposite of what a timeout is for. One such wrapper
hung three CI jobs for two hours each: ``container exec`` wrapped docker in
``timeout``, an ansible.builtin.script task gave the remote shell a tty, and
``docker exec -i`` stopped on the first read.

Text search cannot find this. The wrapper is assembled from a prefix the
module builds and arguments the caller supplies, so ``timeout`` and the
command that reads stdin never meet in one line of source. Detection is on
the parsed tree: any list whose first element is the literal ``timeout`` has
to carry ``--foreground`` among its elements.

``--foreground`` costs the ability to signal a whole process tree; the
signals reach the direct child only. Where that matters more than the stop,
say so with ``# nocheck: timeout-foreground <reason>`` on the line or
directly above it.
"""

from __future__ import annotations

import ast
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "timeout-foreground"
_COMMAND = "timeout"
_FLAG = "--foreground"


def _is_timeout_argv(node: ast.expr) -> bool:
    """Whether a node is a list literal whose first element is ``timeout``.

    Args:
        node: the node to classify.
    """
    if not isinstance(node, ast.List) or not node.elts:
        return False
    first = node.elts[0]
    return isinstance(first, ast.Constant) and first.value == _COMMAND


def _carries_foreground(node: ast.List) -> bool:
    """Whether ``--foreground`` is among a list's constant elements.

    Args:
        node: the argv list.
    """
    return any(
        isinstance(element, ast.Constant) and element.value == _FLAG
        for element in node.elts
    )


def _offenders(rel_path: str, content: str) -> list[str]:
    """Return the timeout argv lists of one module that omit the flag.

    Args:
        rel_path: path relative to the project root.
        content: the file's text.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    lines = content.splitlines()
    found: list[str] = []
    for node in ast.walk(tree):
        if not _is_timeout_argv(node) or _carries_foreground(node):
            continue
        if is_suppressed_at(lines, node.lineno, _RULE, mode="same-or-above"):
            continue
        found.append(f"{rel_path}:{node.lineno}: {ast.unparse(node)}")
    return found


class TestTimeoutArgvRunsInForeground(unittest.TestCase):
    def test_every_constructed_timeout_keeps_its_process_group(self) -> None:
        offenders: list[str] = []
        for path in iter_project_files(extensions=(".py",)):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            try:
                content = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if f'"{_COMMAND}"' not in content and f"'{_COMMAND}'" not in content:
                continue
            offenders.extend(_offenders(rel, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} constructed timeout argv omit {_FLAG}, so the "
            "wrapped command leaves the caller's process group and stops on "
            f"SIGTTIN instead of being killed at the deadline:\n{report}\n\n"
            f"Add {_FLAG}, or keep the group kill and say why the wrapped "
            f"command never reads a terminal with `# nocheck: {_RULE} "
            "<reason>`.",
        )


class TestTimeoutDetection(unittest.TestCase):
    def test_a_bare_timeout_argv_is_reported(self) -> None:
        self.assertEqual(
            ["m.py:1: ['timeout', '15', 'docker', 'ps']"],
            _offenders("m.py", "['timeout', '15', 'docker', 'ps']"),
        )

    def test_a_foreground_timeout_argv_is_accepted(self) -> None:
        self.assertEqual(
            [],
            _offenders("m.py", "['timeout', '--foreground', '15', 'docker', 'ps']"),
        )

    def test_a_list_that_only_mentions_timeout_later_is_ignored(self) -> None:
        self.assertEqual([], _offenders("m.py", "['docker', 'timeout', '15']"))

    def test_a_keyword_timeout_is_not_an_argv(self) -> None:
        self.assertEqual([], _offenders("m.py", "run(cmd, timeout=15)"))

    def test_a_nocheck_suppresses_the_finding(self) -> None:
        source = "# nocheck: timeout-foreground group kill wanted\n['timeout', '5']"
        self.assertEqual([], _offenders("m.py", source))


if __name__ == "__main__":
    unittest.main()
