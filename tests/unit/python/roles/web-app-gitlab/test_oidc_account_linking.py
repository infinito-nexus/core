from __future__ import annotations

import json
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-gitlab"
CONFIG = ROLE / "templates/config/gitlab.yml.j2"
SCRIPT = ROLE / "files/ruby/ensure_platform_admin.rb"
TASK = ROLE / "tasks/utils/platform_admin.yml"
VARS = ROLE / ROLE_FILE_VARS_MAIN


def omniauth(sso: bool) -> dict:
    """
    Args:
        sso: value of both ``GITLAB_OIDC_ENABLED`` and ``GITLAB_LOGIN_SSO``.

    Returns:
        The ``omniauth`` section of the rendered gitlab.yml.
    """
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["to_json"] = json.dumps
    environment.filters["bool"] = bool
    rendered = environment.from_string(read_text(str(CONFIG))).render(
        GITLAB_HOSTNAME="gitlab.example.org",
        GITLAB_WEB_PORT=8080,
        GITLAB_TLS_ENABLED=True,
        GITLAB_EMAIL_ENABLED=False,
        GITLAB_OBJSTORE_ENABLED=False,
        GITLAB_OIDC_ENABLED=sso,
        GITLAB_LOGIN_SSO=sso,
        GITLAB_LOGIN_2FA=False,
        GITLAB_OIDC_LABEL="Keycloak",
        GITLAB_OIDC_ISSUER="https://auth.example.org/realms/main",
        GITLAB_OIDC_UID_FIELD="preferred_username",
        GITLAB_OIDC_CLIENT_ID="gitlab",
        GITLAB_OIDC_CLIENT_SECRET="",
        GITLAB_OIDC_REDIRECT_URI="https://gitlab.example.org/users/auth/openid_connect/callback",
        GITLAB_GITALY_TOKEN="",
        GITLAB_GITALY_SERVICE_NAME="gitaly",
        GITLAB_GITALY_PORT=8075,
        GITLAB_SSH_PORT=22,
        GITLAB_SIDEKIQ_HEALTH_PORT=8092,
    )
    return load_yaml_str(rendered)["production"]["omniauth"]


class TestGitlabOidcAccountLinking(unittest.TestCase):
    def test_no_sso_login_links_an_account_by_email(self) -> None:
        self.assertIs(
            omniauth(sso=True)["auto_link_user"],
            False,
            "Gitlab::Auth::OAuth::User#find_user falls back to find_by_email when "
            "auto_link_user names the provider (gitlab v19.5.3-ee "
            "lib/gitlab/auth/o_auth/user.rb:83-93,163-168,318-324), so a Keycloak user "
            "who holds another account's address signs in as that account",
        )
        self.assertEqual(omniauth(sso=False), {"enabled": False})

    def test_the_administrator_identity_is_seeded_by_username(self) -> None:
        script = read_text(str(SCRIPT))
        reason = (
            "without auto_link_user, the administrator's SSO login reaches its account "
            "only through Identity(provider: openid_connect, extern_uid: "
            "preferred_username), found by find_by_uid_and_provider"
        )
        self.assertIn("sso_uid = ENV.fetch('GITLAB_ADMIN_SSO_UID')", script, reason)
        self.assertIn(
            "user.identities.find_or_initialize_by(provider: 'openid_connect')",
            script,
            reason,
        )
        self.assertIn("identity.extern_uid = sso_uid", script, reason)
        self.assertIn("identity&.save!", script, reason)
        self.assertIn(
            "Identity.with_extern_uid('openid_connect', sso_uid).where.not(user_id: user.id)",
            script,
            "an extern_uid held by another account must stop the deploy instead of "
            "leaving the administrator unreachable through SSO",
        )

        task = load_yaml_str(read_text(str(TASK)))[1]
        self.assertIn(
            "-e GITLAB_ADMIN_SSO_UID", task["ansible.builtin.shell"]["cmd"], reason
        )
        self.assertEqual(
            task["environment"]["GITLAB_ADMIN_SSO_UID"],
            "{{ GITLAB_ADMIN_USERNAME if (GITLAB_OIDC_ENABLED | bool and "
            "GITLAB_LOGIN_SSO | bool) else '' }}",
            reason,
        )
        self.assertEqual(
            load_yaml_str(read_text(str(VARS)))["GITLAB_OIDC_UID_FIELD"],
            "{{ OIDC.ATTRIBUTES.USERNAME }}",
            "the seeded extern_uid is the username, so GitLab must take the OIDC uid "
            "from preferred_username",
        )


if __name__ == "__main__":
    unittest.main()
