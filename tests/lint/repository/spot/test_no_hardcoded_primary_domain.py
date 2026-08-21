"""Forbid writing the primary domain literally instead of deriving it.

``default.env`` declares ``INFINITO_DOMAIN`` and is the single source of truth
for the CI/dev project domain. Every consumer is expected to derive from it --
Ansible through ``DOMAIN_PRIMARY``, Python through
``utils.domains.default_primary.default_domain_primary()``, shell through the
generated ``.env``. A copy of the value somewhere else is a second source that
nobody updates when the first one changes, and it fails in the least helpful
way: the code keeps running and quietly talks about the wrong host.

That is not hypothetical. ``integration_mastodon.spec.js`` asserted the
provisioned partner host equalled ``microblog.<domain>`` as a literal, so the
spec passed on a clearnet node and failed on an onion one although the product
was correct in both.

The value searched for is read from ``default.env`` at test time, so this rule
follows the SPOT rather than repeating it.

Scope: every git-tracked file except ``default.env`` itself, ``.md``
documentation, and three places where a concrete host is the point rather than a
copy -- the test trees (``tests/`` and ``scripts/tests/``) whose fixtures assert
against a named host, and ``inventories/``, where declaring the real values is
what an inventory is for. Gitignored build output is skipped too: a generated
``.env`` carries the value because it correctly derived it.

Per-line opt-out: ``# nocheck: hardcoded-primary-domain`` on the offending line
or the immediately preceding non-empty line, with a reason. Legitimate cases are
help texts, example output in a docstring, and markers written into files a user
reads.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_non_ignored_files, read_text
from utils.env.parser import parse_static_env

from . import PROJECT_ROOT

_RULE = "hardcoded-primary-domain"
_SPOT_FILE = "default.env"
_SPOT_KEY = "INFINITO_DOMAIN"
_SKIP_DIRS = (".claude/", "build/", "inventories/", "scripts/tests/")


def _spot_domain() -> str:
    """The literal this rule hunts for, taken from the SPOT it defends."""
    return parse_static_env(PROJECT_ROOT / _SPOT_FILE)[_SPOT_KEY].strip()


def _is_scan_target(rel_path: str) -> bool:
    """Files whose content must not carry the literal.

    Args:
        rel_path: repository-relative path of the candidate file.
    """
    if rel_path == _SPOT_FILE or rel_path.endswith(".md"):
        return False
    return not rel_path.startswith(_SKIP_DIRS)


def _collect_findings(domain: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path_str in iter_non_ignored_files(exclude_tests=True):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not _is_scan_target(rel):
            continue
        try:
            content = read_text(path_str)
        except (OSError, UnicodeDecodeError):
            continue
        if domain not in content:
            continue
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            if domain not in line:
                continue
            if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                continue
            findings.append((rel, idx + 1, line.strip()))
    return sorted(set(findings))


class TestNoHardcodedPrimaryDomain(unittest.TestCase):
    def test_primary_domain_is_derived_not_written_out(self) -> None:
        domain = _spot_domain()
        self.assertTrue(domain, f"{_SPOT_KEY} is empty in {_SPOT_FILE}")

        findings = _collect_findings(domain)
        if not findings:
            return

        formatted = "\n".join(
            f"- {rel}:{line_no}: {text}" for rel, line_no, text in findings
        )
        self.fail(
            f"Found the primary domain {domain!r} written out instead of derived. "
            f"{_SPOT_FILE} declares {_SPOT_KEY} and is the single source of truth; "
            "a second copy is one nobody updates.\n\n"
            "  Ansible:  DOMAIN_PRIMARY\n"
            "  Python:   utils.domains.default_primary.default_domain_primary()\n"
            "  shell:    the generated .env\n\n"
            f"Affected:\n{formatted}\n\n"
            f"Per-line opt-out: `# nocheck: {_RULE}` with a reason."
        )


if __name__ == "__main__":
    unittest.main()
