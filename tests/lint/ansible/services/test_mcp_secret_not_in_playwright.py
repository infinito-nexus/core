"""Lint: no MCP credential reaches a Playwright run.

Playwright keeps a trace of every run it is told to retain, and a value handed
to the browser through ``playwright.env.j2`` is in it: request headers, the
environment dump, the network log. A provider bearer that lands there survives
in a CI artifact long after the deploy that minted it, readable by anyone who
can download the bundle.

The test suite already respects this. The authenticated MCP contract check is a
CLI test rather than a spec precisely because the spec would capture the bearer,
and the guest specs ask the anonymous question, which needs no credential at
all. This rule keeps that arrangement from eroding one convenient environment
variable at a time.

Secret URL components count the same: a provider whose endpoint path carries a
generated key hands out a working URL, not merely a hint.

An application's own login password is a different thing and stays allowed; the
personas need it, and it grants the caller's own rights rather than the
deployment's provider identity.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-secret-not-in-playwright`` on the offending line or the
  non-empty line above it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "mcp-secret-not-in-playwright"
_ENV_TEMPLATE = "templates/playwright.env.j2"

_MCP_SECRET = re.compile(
    r"lookup\(\s*['\"]mcp_credential['\"]"
    r"|secrets\.credentials\.mcp_"
    r"|mcp\.credential\b"
    r"|key_credential",
)


def _playwright_envs() -> list[tuple[str, str]]:
    roles_prefix = str(PROJECT_ROOT / "roles") + "/"
    return [
        (path, content)
        for path, content in iter_project_files_with_content(
            extensions=(".j2",), exclude_tests=True
        )
        if path.startswith(roles_prefix) and path.endswith(_ENV_TEMPLATE)
    ]


class TestMcpSecretNotInPlaywright(unittest.TestCase):
    def test_no_playwright_env_renders_an_mcp_secret(self) -> None:
        findings: list[str] = []
        for path, content in _playwright_envs():
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _MCP_SECRET.search(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
                findings.append(f"{rel}:{idx + 1}: {line.strip()}")

        self.assertEqual(
            [],
            sorted(findings),
            f"MCP credential(s) handed to a Playwright run ({len(findings)}); "
            f"the trace outlives the deploy and travels in the CI artifact:\n"
            + "\n".join(f"  - {f}" for f in sorted(findings)),
        )

    def test_the_scan_reads_playwright_env_templates(self) -> None:
        self.assertTrue(
            _playwright_envs(),
            f"no role ships a {_ENV_TEMPLATE}, so the rule would pass "
            "vacuously; check that the scan still reads the right topic",
        )

    def test_the_pattern_matches_a_real_credential_reference(self) -> None:
        """A pattern that matches nothing anywhere would pass silently."""
        matched = any(
            _MCP_SECRET.search(content)
            for _path, content in iter_project_files_with_content(
                extensions=(".yml", ".j2"), exclude_tests=True
            )
        )
        self.assertTrue(
            matched,
            "the MCP-secret pattern matches nothing in the repository, so the "
            "rule cannot be distinguishing anything; check that the credential "
            "lookup is still spelled the way this pattern expects",
        )


if __name__ == "__main__":
    unittest.main()
