from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-gitea"
PATCH = ROLE / "files/patch/oauth2/account-linking-by-name.patch"
HUNK = re.compile(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@")


def _diff_lines() -> list[str]:
    """Return the patch from its first file header on.

    Returns:
        The diff lines without the leading description.
    """
    lines = read_text(str(PATCH)).splitlines()
    return lines[next(i for i, line in enumerate(lines) if line.startswith("--- ")) :]


def _body(prefix: str) -> list[str]:
    """Return the hunk lines of one side of the patch.

    Args:
        prefix: ``"-"`` for removed or ``"+"`` for added lines.

    Returns:
        Those lines without their prefix.
    """
    return [
        line[1:]
        for line in _diff_lines()
        if line.startswith(prefix) and not line.startswith(("--- ", "+++ "))
    ]


class TestGiteaAccountLinkingPatch(unittest.TestCase):
    def test_the_patch_targets_only_the_account_linking_code(self):
        headers = [line for line in _diff_lines() if line.startswith(("--- ", "+++ "))]
        self.assertEqual(
            headers,
            ["--- a/routers/web/auth/auth.go", "+++ b/routers/web/auth/auth.go"],
        )

    def test_the_primary_email_lookup_is_removed(self):
        reason = (
            "createUserInContext links an OAuth2 sign-in to the account holding its "
            "primary email when no account has its name (gitea v28.2.0 "
            "routers/web/auth/auth.go:639), which hands any account to whoever holds "
            "its address at the identity provider"
        )
        self.assertTrue(
            any("GetIndividualUserByPrimaryEmail" in line for line in _body("-")),
            reason,
        )
        self.assertFalse(any("Email(ctx" in line for line in _body("+")), reason)

    def test_an_email_only_collision_is_refused_on_the_sign_in_page(self):
        added = "\n".join(_body("+"))
        self.assertIn('ctx.Flash.Error(ctx.Tr("form.email_been_used"))', added)
        self.assertIn('ctx.Redirect(setting.AppSubURL + "/user/login")', added)
        self.assertIn("return false", added)

    def test_every_hunk_header_counts_its_lines(self):
        lines = _diff_lines()
        starts = [i for i, line in enumerate(lines) if HUNK.match(line)]
        self.assertTrue(starts)
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(lines)
            body = lines[start + 1 : end]
            _, old, _, new = (int(group) for group in HUNK.match(lines[start]).groups())
            with self.subTest(hunk=lines[start]):
                self.assertEqual(
                    old, sum(1 for line in body if line[:1] in (" ", "-", ""))
                )
                self.assertEqual(
                    new, sum(1 for line in body if line[:1] in (" ", "+", ""))
                )

    def test_the_build_applies_both_patches_in_order(self):
        variables = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
        self.assertEqual(
            variables["GITEA_PATCH_FILES"],
            [
                "oauth2/redirect-uri-public-url.patch",
                "oauth2/account-linking-by-name.patch",
            ],
        )
        for name in variables["GITEA_PATCH_FILES"]:
            self.assertTrue((ROLE / "files/patch" / name).is_file(), name)
        dockerfile = read_text(str(ROLE / "files/Dockerfile"))
        self.assertIn("ARG GITEA_PATCH_FILES", dockerfile)
        self.assertIn("xargs git apply", dockerfile)
        self.assertIn(
            "GITEA_PATCH_FILES: \"{{ GITEA_PATCH_FILES | join(' ') }}\"",
            read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE)),
        )


if __name__ == "__main__":
    unittest.main()
