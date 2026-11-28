from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

SETTINGS = PROJECT_ROOT / "roles/web-app-discourse/files/ruby/apply_settings.rb"


def oidc_block_settings() -> dict[str, str]:
    """Read the SiteSetting assignments inside the OIDC branch of apply_settings.rb.

    Returns:
        Each assigned setting name mapped to its Ruby expression.
    """
    block = read_text(str(SETTINGS)).split(
        'if ENV.fetch("DISCOURSE_OIDC_ENABLED") == "true"', 1
    )[1]
    return dict(re.findall(r"^\s+SiteSetting\.(\w+) = (.+)$", block, re.MULTILINE))


class TestDiscourseOidcEmailMatching(unittest.TestCase):
    def test_email_matching_requires_a_verified_claim(self) -> None:  # nocheck: test.text-presence -- parses the OIDC branch assignments into a setting map  # fmt: skip
        settings = oidc_block_settings()
        self.assertEqual(
            settings.get("openid_connect_email_verified_claim_fallback"),
            "false",
            "find_user_by_email links only when primary_email_verified? holds, and "
            "primary_email_verified? answers this fallback when the email_verified claim "
            "is missing (discourse v2026.10.0 lib/auth/managed_authenticator.rb:131-134, "
            "plugins/discourse-openid-connect/lib/openid_connect_authenticator.rb:32-42); "
            "true would link any account by an unproven address",
        )

    def test_email_matching_is_pinned(self) -> None:  # nocheck: test.text-presence -- parses the OIDC branch assignments into a setting map  # fmt: skip
        self.assertEqual(
            oidc_block_settings().get("openid_connect_match_by_email"),
            "true",
            "the first SSO login of the administrator and of every account created "
            "through LDAP or a password reaches it only by its verified address, because "
            "the OpenID Connect authenticator cannot match by username and the role "
            "cannot know the Keycloak sub to pre-link a UserAssociatedAccount",
        )


if __name__ == "__main__":
    unittest.main()
