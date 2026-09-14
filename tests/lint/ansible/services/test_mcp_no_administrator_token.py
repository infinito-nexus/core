"""Lint: MCP task code reads the declared credential owner, never the administrator.

``meta/mcp.yml`` names the principal a provider's secret belongs to, and
``credential.owner`` must not be ``administrator``: a provider that borrows the
deployment administrator's token hands every client that account's rights, and
revoking one provider then disarms all of them.

The declaration alone does not enforce that. Six providers used to write their
token to the store under the declared owner and read it back from
``users.administrator.tokens``, which the store does not carry. The read never
matched, so the "do I already have one?" check was dead and every deploy minted
a fresh credential.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-no-administrator-token`` on, or directly above, the line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

_RULE = "mcp-no-administrator-token"

_ADMIN_TOKEN_RE = re.compile(
    r"""lookup\(\s*['"]users['"]\s*,\s*['"]administrator['"]\s*\)\s*
        (?:\.tokens|\[\s*['"]tokens['"]\s*\])""",
    re.VERBOSE,
)


def _mcp_task_files() -> list[tuple[str, str]]:
    """Return ``(path, content)`` for every MCP task file under ``roles/``."""
    files = []
    for path, content in iter_project_files_with_content(extensions=(".yml",)):
        parts = Path(path).parts
        if "roles" not in parts or "tasks" not in parts:
            continue
        if "mcp" not in Path(path).stem and "mcp" not in parts:
            continue
        files.append((path, content))
    return files


def administrator_token_reads() -> list[str]:
    """Return one finding per MCP task line reading the administrator's tokens."""
    findings = []
    for path, content in _mcp_task_files():
        lines = content.splitlines()
        for number, line in enumerate(lines, start=1):
            if not _ADMIN_TOKEN_RE.search(line):
                continue
            if is_suppressed_at(lines, number, _RULE):
                continue
            findings.append(
                f"{path}:{number}: reads users.administrator.tokens; MCP task "
                f"code must resolve mcp.credential.owner instead"
            )
    return findings


class TestMcpNoAdministratorToken(unittest.TestCase):
    def test_no_mcp_task_borrows_the_administrator_token(self) -> None:
        findings = administrator_token_reads()
        self.assertEqual(
            [],
            findings,
            f"MCP task code borrowing the administrator token ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_reaches_the_mcp_task_files(self) -> None:
        self.assertTrue(
            _mcp_task_files(),
            "no MCP task file was scanned, so the rule would pass vacuously",
        )


if __name__ == "__main__":
    unittest.main()
