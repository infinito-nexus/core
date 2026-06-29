"""Lint the checked-out git branch name against the naming policy.

The SPOT for valid prefixes and full-name patterns is
``docs/contributing/artefact/git/branch.md`` (Naming Conventions). A branch
that uses an unknown prefix (e.g. ``feat/`` instead of ``feature/``) or a
non-kebab-case description fails this lint, so the mistake is caught locally
before it ever reaches a push or pull request.
"""

from __future__ import annotations

import re
import subprocess
import unittest

from . import PROJECT_ROOT

EXEMPT_BRANCHES = {"main", "master", "HEAD"}

KEBAB = r"[a-z0-9]+(?:-[a-z0-9]+)*"

BRANCH_PATTERNS = (
    rf"feature/{KEBAB}(?:/{KEBAB})*",
    rf"fix/{KEBAB}(?:/{KEBAB})+",
    rf"update/{KEBAB}(?:/{KEBAB})*",
    rf"chore/{KEBAB}(?:/{KEBAB})*",
    rf"documentation/{KEBAB}(?:/{KEBAB})*",
    rf"agent/{KEBAB}(?:/{KEBAB})*",
    r"alert-autofix-\d+",
    r"dependabot/.+",
)

BRANCH_RE = re.compile(r"^(?:" + "|".join(BRANCH_PATTERNS) + r")$")

VALID_PREFIXES = (
    "feature",
    "fix",
    "update",
    "chore",
    "documentation",
    "agent",
    "alert-autofix",
    "dependabot",
)


def current_branch() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


class TestBranchName(unittest.TestCase):
    """Fail when the checked-out branch violates the branch-naming policy."""

    def test_current_branch_name_is_valid(self):
        branch = current_branch()
        if branch is None or branch in EXEMPT_BRANCHES:
            self.skipTest(f"branch {branch!r} is exempt or unavailable")

        self.assertRegex(
            branch,
            BRANCH_RE,
            msg=(
                f"Branch '{branch}' violates the naming policy in "
                "docs/contributing/artefact/git/branch.md.\n"
                f"Valid prefixes: {', '.join(VALID_PREFIXES)}.\n"
                "Examples: feature/web-app-semaphore, "
                "feature/web-app-matomo/ldap-integration, "
                "fix/dns-resolution/taiga-123, documentation/contributing-setup."
            ),
        )


if __name__ == "__main__":
    unittest.main()
