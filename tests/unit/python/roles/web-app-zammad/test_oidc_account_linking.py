from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

ROLE = PROJECT_ROOT / "roles/web-app-zammad"
SETTINGS = ROLE / "files/ruby/apply/oidc_settings.rb"
TASKS = ROLE / "tasks/01_manager_ops/oidc.yml"
PATCH = ROLE / "templates/zz/oidc/group_role_mapping.rb.j2"
OIDC_TASK = "📌 apply OIDC settings in Zammad (post-bootstrap; idempotent)"


def oidc_task() -> dict:
    return next(
        task
        for task in load_yaml_str(read_text(str(TASKS)))
        if task["name"] == OIDC_TASK
    )


class TestZammadOidcAccountLinking(unittest.TestCase):
    def test_no_sso_login_links_an_account_by_email(self) -> None:
        source = read_text(str(SETTINGS))
        self.assertIn(
            'Setting.set("auth_third_party_auto_link_at_inital_login", false)',
            source,
            "Authorization::Provider#fetch_user runs find_user only while this setting "
            "is on, and the OpenID Connect find_user falls back to User.find_by(email:) "
            "(zammad 7.1.2 app/models/authorization/provider.rb:22-40, "
            "provider/openid_connect.rb:6-14), which hands a Keycloak user holding "
            "another account's address that account",
        )
        self.assertNotIn(
            'Setting.set("auth_third_party_auto_link_at_inital_login", true)', source
        )

    def test_the_administrator_authorization_is_prelinked_by_login(self) -> None:
        source = read_text(str(SETTINGS))
        reason = (
            "with auto-link off, an administrator that already exists in Zammad reaches "
            "its account through SSO only by an Authorization(provider, uid) whose uid is "
            "the preferred_username Zammad receives as uid; without it create_from_hash! "
            "collides with the administrator's email and the sign-in fails"
        )
        self.assertIn(
            'User.find_by(login: ENV.fetch("OIDC_ADMIN_LOGIN").downcase)', source
        )
        self.assertIn(
            'Authorization.find_or_initialize_by(provider: "openid_connect", uid: admin.login)',
            source,
            reason,
        )
        task = oidc_task()
        self.assertIn(
            "-e OIDC_ADMIN_LOGIN", task["ansible.builtin.shell"]["cmd"], reason
        )
        self.assertEqual(
            task["environment"]["OIDC_ADMIN_LOGIN"],
            "{{ ZAMMAD_ADMINISTRATOR.username }}",
            reason,
        )
        self.assertEqual(
            task["environment"]["OIDC_UID_FIELD"],
            "{{ OIDC.ATTRIBUTES.USERNAME }}",
            reason,
        )

    def test_directory_accounts_link_by_login_not_by_email(self) -> None:
        source = read_text(str(PATCH))
        reason = (
            "the LDAP import creates every directory user before its first SSO login; "
            "with auto-link off, create_from_hash must receive that account, found by "
            "login = uid, or Zammad tries to create a duplicate and refuses its email"
        )
        self.assertIn(
            'User.where("source LIKE ?", "Ldap::%").find_by(login: uid)', source, reason
        )
        self.assertIn(
            "super(hash, user || _zammad_oidc_directory_user(hash))", source, reason
        )
        helper = source.split("define_method(:_zammad_oidc_directory_user)", 1)[
            1
        ].split("define_method(", 1)[0]
        self.assertNotIn("email", helper, reason)


if __name__ == "__main__":
    unittest.main()
