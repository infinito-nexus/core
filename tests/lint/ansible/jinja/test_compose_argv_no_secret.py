from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-argv-secret"

_SCAN_PREFIX = "roles/"
_ARGV_KEY = re.compile(
    r"^(?P<indent>\s*)(?:-\s+)?(?:command|entrypoint|healthcheck|test)\s*:"
)
_EXPRESSION = re.compile(r"\{\{(.*?)\}\}")
_CREDENTIAL = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|api_?key|private_?key|credential)"
)
_DESCRIBES_CREDENTIAL = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|api_?key|private_?key|credential)\w*"
    r"_(?:file|path|dir|id|name|user|username|hash|length)\b"
)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _argv_secret_lines(lines: list[str]) -> list[int]:
    """Return the 1-based lines that render a credential into an argv block.

    Args:
      lines: the template's lines.

    Returns:
      every line inside a ``command``, ``entrypoint``, ``healthcheck`` or
      ``test`` value whose Jinja expression names a credential.
    """
    found: list[int] = []
    block_indent: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        key = _ARGV_KEY.match(line)
        if key:
            block_indent = len(key.group("indent"))
        elif (
            block_indent is not None
            and stripped
            and not stripped.startswith("{%")
            and _indent(line) <= block_indent
        ):
            block_indent = None
        if block_indent is None:
            continue
        for expression in _EXPRESSION.findall(line):
            if _CREDENTIAL.search(expression) and not _DESCRIBES_CREDENTIAL.search(
                expression
            ):
                found.append(index + 1)
                break
    return found


class TestComposeArgvNoSecret(unittest.TestCase):
    def test_compose_argv_renders_no_credential(self) -> None:
        findings: list[str] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith(_SCAN_PREFIX) or "/templates/" not in rel:
                continue
            lines = content.splitlines()
            findings.extend(
                f"- {rel}:{line_no}: {lines[line_no - 1].strip()}"
                for line_no in _argv_secret_lines(lines)
                if not is_suppressed_at(lines, line_no, _RULE, mode="same-or-above")
            )

        self.assertFalse(
            findings,
            "A credential is rendered into a container's command, entrypoint or "
            "healthcheck, where `docker inspect` and the host's `ps` show it. Put "
            "it into the container environment (env file or `environment:`) and "
            "read it there at runtime, e.g. `$$REDIS_PASSWORD` in a CMD-SHELL "
            "or a tool's own variable such as REDISCLI_AUTH. Mark a deliberate "
            f"exception with `# nocheck: {_RULE}`.\n\nOffenders:\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
