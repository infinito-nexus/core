"""Flag env-file template lines that wrap the value in literal double
quotes (``KEY="..."``). compose strips those quotes when parsing the
env file, but ``docker stack deploy`` preserves them literally - the
container then sees ``KEY="value"`` instead of ``KEY=value`` and code
that uses ``int(os.environ['KEY'])`` or parses URLs / DSNs from the env
breaks.

Allowed forms:

* ``KEY=value`` (unquoted; spaces are fine in env-file syntax)
* ``KEY={{ ... | dotenv_quote }}`` (explicit escape that produces the
  correctly escaped value for both modes)

Rejected: ``KEY="{{ ... }}"`` and ``KEY="literal-value"`` without the
``dotenv_quote`` filter.

Per-line opt-out: ``# nocheck: env-file-literal-quoted-value`` on the
offending line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "env-file-literal-quoted-value"

_LITERAL_QUOTED = re.compile(r'^\s*[A-Z_][A-Z0-9_]*\s*=\s*"')
_DOTENV_QUOTE = re.compile(r"\|\s*dotenv_quote\b")


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if "/templates/" not in rel_path:
        return False
    if not rel_path.endswith(".j2"):
        return False
    base = Path(rel_path).name
    return ".env" in base or base.endswith("env.j2")


class TestEnvFileTemplateNoLiteralQuotes(unittest.TestCase):
    def test_env_templates_have_no_literal_quoted_values(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _LITERAL_QUOTED.match(line):
                    continue
                if _DOTENV_QUOTE.search(line):
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
                "Found env-file template lines wrapping the value in literal "
                "double quotes. compose strips them, swarm preserves them "
                'literally - the container sees `KEY="value"` instead of '
                "`KEY=value` and `int()` / URL parsers break.\n\n"
                "Fix: drop the surrounding quotes (env-file syntax allows "
                "spaces unquoted), or use `KEY={{ ... | dotenv_quote }}` "
                "for values with shell metachars / dollars. Mark with "
                "`# nocheck: env-file-literal-quoted-value` only when the "
                "consumer specifically needs the literal quotes (very rare).\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
