"""An env value that renders more than one word must be quoted.

``KEY=one two`` is not an assignment of two words. The shell reads it as
``KEY=one`` prefixed to the command ``two``, so the variable is set for that
command only and is unset afterwards. Under ``set -u`` the consumer then dies
on ``KEY: unbound variable`` while the rendered file plainly shows the value,
which is how ``AGENT_PLATFORMS_OFFERED=hermes openclaw`` took down the compose
rows of svc-ai-agent-broker and web-app-openwebui in run 35889056152.

Only ``join`` with a space separator is flagged. A comma or a semicolon
produces one word and is safe unquoted, and ``to_json`` output is already
covered by the repository's quoting convention.

Per-line opt-out: ``# nocheck: env-space-value-unquoted``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, iter_project_files_with_content

_RULE = "env-space-value-unquoted"

_ASSIGNMENT = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
_SPACE_JOIN = re.compile(r"join\(\s*(['\"]) \1\s*\)")
_QUOTED = re.compile(r"^(['\"]).*\1$")


def renders_unquoted_words(line: str) -> bool:
    """Whether this assignment can put a space into an unquoted value."""
    match = _ASSIGNMENT.match(line)
    if not match:
        return False
    value = match.group("value").strip()
    if not _SPACE_JOIN.search(value):
        return False
    if "dotenv_quote" in value:
        return False
    return not _QUOTED.match(value)


class TestEnvValueSpaceQuoted(unittest.TestCase):
    def test_no_unquoted_space_joined_env_value(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.endswith("env.j2"):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not renders_unquoted_words(line):
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
                "Found env assignments whose value joins on a space without "
                "being quoted. The shell treats the second word as a command "
                "and leaves the variable unset, so a consumer running under "
                "`set -u` dies on an unbound variable that the rendered file "
                "appears to contain.\n\n"
                "Fix: append `| dotenv_quote`.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
