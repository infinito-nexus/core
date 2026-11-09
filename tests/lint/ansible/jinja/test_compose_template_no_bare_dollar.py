"""Flag a ``$`` in a compose template that docker cannot read as a variable.

``docker stack config`` refuses the whole stack file with ``invalid
interpolation format for services.<svc>.command.[]: "..."; you may need to
escape any $ with another $``. ``docker compose config`` accepts the same file
silently and even re-emits the character as ``$$``, so the compose rows of a CI
run are green while every swarm row of the same role dies at validation. Only
the swarm path can catch this, which is why it is caught here instead.

A regex anchor is the usual source: ``-allowGET=^(/v[0-9.]+)?/(...)$`` ends in a
``$`` that starts no variable name. Escaping it as ``$$`` is correct for both
runtimes: ``docker stack config`` unescapes it to one ``$``, and a container run
under compose receives one ``$`` in its argv.

Per-line opt-out: ``# nocheck: compose-bare-dollar`` on the offending line or
the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT, is_main_compose_template

_RULE = "compose-bare-dollar"

_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_BARE_DOLLAR = re.compile(r"\$(?![A-Za-z_{$])")


def bare_dollar_columns(line: str) -> list[int]:
    """The 1-based columns of every ``$`` docker would refuse, Jinja removed.

    Args:
        line: one raw template line.

    Returns:
        The columns, empty when the line is clean. A ``$`` inside a Jinja
        expression is consumed at render time and never reaches docker, so the
        expressions are blanked rather than skipped, which keeps the columns
        pointing at the raw line.
    """
    masked = _JINJA.sub(lambda match: " " * len(match.group(0)), line)
    columns = []
    index = 0
    while index < len(masked):
        if masked[index] != "$":
            index += 1
            continue
        if masked.startswith("$$", index):
            index += 2
            continue
        if _BARE_DOLLAR.match(masked, index):
            columns.append(index + 1)
        index += 1
    return columns


class TestComposeTemplateNoBareDollar(unittest.TestCase):
    def test_no_bare_dollar_in_compose_template(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not is_main_compose_template(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not bare_dollar_columns(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found a `$` in a compose template that docker cannot read as "
                "a variable reference. `docker stack config` refuses the whole "
                "stack file over it while `docker compose config` accepts it "
                "silently, so every swarm row of the role fails and no compose "
                "row reports anything.\n\n"
                "Fix: double it (`$$`). Both runtimes unescape it back to one "
                "`$` in the container. Mark with `# nocheck: "
                "compose-bare-dollar` only where docker really is meant to "
                "interpolate.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
