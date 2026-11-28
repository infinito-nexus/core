from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

ROLE = PROJECT_ROOT / "roles/web-app-zammad"
SETTINGS = ROLE / "files/ruby/apply/oidc_settings.rb"
TASKS = ROLE / "tasks/01_manager_ops/oidc.yml"
OIDC_TASK = "📌 apply OIDC settings in Zammad (post-bootstrap; idempotent)"


def oidc_task() -> dict:
    return next(
        task
        for task in load_yaml_str(read_text(str(TASKS)))
        if task["name"] == OIDC_TASK
    )


class TestZammadOidcAccountLinking(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
