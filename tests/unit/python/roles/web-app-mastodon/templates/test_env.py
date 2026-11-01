from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLE = PROJECT_ROOT / "roles/web-app-mastodon"
ENV = ROLE / "templates/env.j2"
ADMIN_SCRIPT = ROLE / "files/ruby/ensure/administrator.rb"
ADMIN_TASK = ROLE / "tasks/05_administrator.yml"


def env_values() -> dict[str, str]:
    """Read the literal ``KEY=value`` lines of the Mastodon env template.

    Returns:
        Each variable name mapped to its unrendered value.
    """
    return dict(
        re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", read_text(str(ENV)), re.MULTILINE)
    )


class TestMastodonSsoAccountLinking(unittest.TestCase):
    def test_keycloak_email_verified_decides(self) -> None:
        self.assertEqual(
            env_values()["OIDC_SECURITY_ASSUME_EMAIL_IS_VERIFIED"],
            "false",
            "User::Omniauthable#email_from_auth ORs assume_email_is_verified into "
            "email_is_verified (mastodon v4.6.2 omniauthable.rb:86-93), so 'true' marks "
            "every address Keycloak sends as verified, whatever its email_verified says",
        )

    def test_an_sso_login_never_reattaches_by_email(self) -> None:
        self.assertEqual(
            env_values()["ALLOW_UNSAFE_AUTH_PROVIDER_REATTACH"],
            "false",
            "reattach_for_auth hands an SSO login the local user that holds the same "
            "email (omniauthable.rb:45-64), so a Keycloak user who sets the "
            "administrator's address takes over the administrator account",
        )

    def test_the_administrator_identity_is_prelinked_by_username(self) -> None:
        script = read_text(str(ADMIN_SCRIPT))
        reason = (
            "without reattach, find_for_omniauth reaches an existing account only "
            "through Identity(provider, uid); the administrator's SSO login must find "
            "a row with uid = preferred_username (OIDC_UID_FIELD) bound to its account"
        )
        self.assertIn(
            'Identity.find_or_initialize_by(provider: "openid_connect", uid: sso_uid)',
            script,
            reason,
        )
        self.assertIn("identity.user = user", script, reason)
        self.assertEqual(
            env_values()["OIDC_UID_FIELD"], "{{ OIDC.ATTRIBUTES.USERNAME }}"
        )
        self.assertRegex(
            read_text(str(ADMIN_TASK)),
            r"MASTODON_ADMIN_SSO_UID=\{\{ \(lookup\('users', 'platform_administrator'\)"
            r"\.username if MASTODON_OIDC_ENABLED \| bool else ''\) \| quote \}\}",
            reason,
        )


if __name__ == "__main__":
    unittest.main()
