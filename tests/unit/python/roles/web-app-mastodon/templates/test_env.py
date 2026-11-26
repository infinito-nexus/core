from __future__ import annotations

import shlex
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles/web-app-mastodon"
ENV = ROLE / "templates/env.j2"
ADMIN_SCRIPT = ROLE / "files/ruby/ensure/administrator.rb"
ADMIN_TASK = ROLE / "tasks/05_administrator.yml"
OIDC = {
    "BUTTON_TEXT": "Keycloak",
    "CLIENT": {
        "ISSUER_URL": "https://auth.example.org/realms/main",
        "ID": "mastodon",
        "SECRET": "",
    },
    "ATTRIBUTES": {"USERNAME": "preferred_username"},
}


def _environment() -> Environment:
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = bool
    environment.filters["quote"] = shlex.quote
    return environment


def env_values() -> dict[str, str]:
    """
    Returns:
        The ``KEY=VALUE`` pairs the OIDC block of env.j2 renders with OIDC on.
    """
    lines = read_text(str(ENV)).splitlines()
    start = lines.index("{% if MASTODON_OIDC_ENABLED | bool %}")
    end = lines.index("{% endif %}", start)
    rendered = (
        _environment()
        .from_string("\n".join(lines[start : end + 1]))
        .render(
            MASTODON_OIDC_ENABLED=True,
            MASTODON_LOGIN_NATIVE=False,
            OIDC=OIDC,
            RBAC={"GROUP": {"CLAIM": "groups"}},
            application_id="web-app-mastodon",
            lookup=lambda *_terms, **_kwargs: "https://mastodon.example.org/",
        )
    )
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


def admin_sso_uid(oidc: bool) -> str:
    """
    Args:
        oidc: value of ``MASTODON_OIDC_ENABLED``.

    Returns:
        The ``MASTODON_ADMIN_SSO_UID`` the administrator task hands its script.
    """
    task = load_yaml_any(str(ADMIN_TASK))[0]
    command = (
        _environment()
        .from_string(task["ansible.builtin.shell"])
        .render(
            MASTODON_OIDC_ENABLED=oidc,
            MASTODON_LOCAL_CID="mastodon",
            lookup=lambda *_terms: {
                "username": "administrator",
                "email": "administrator@example.org",
            },
        )
    )
    return next(
        arg.split("=", 1)[1]
        for arg in shlex.split(command)
        if arg.startswith("MASTODON_ADMIN_SSO_UID=")
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
            env_values()["OIDC_UID_FIELD"], OIDC["ATTRIBUTES"]["USERNAME"], reason
        )
        self.assertEqual(admin_sso_uid(True), "administrator", reason)
        self.assertEqual(admin_sso_uid(False), "")


if __name__ == "__main__":
    unittest.main()
