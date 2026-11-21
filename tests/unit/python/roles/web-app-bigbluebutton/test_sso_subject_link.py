"""Greenlight links an SSO login by the Keycloak subject, never by e-mail."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "web-app-bigbluebutton"


def sso_block(env):
    match = re.search(
        r"\{% if BBB_LOGIN_SSO \| bool %\}(.*?)\{% endif %\}", env, re.DOTALL
    )
    return match.group(1)


class GreenlightSubjectLinkTests(unittest.TestCase):
    def setUp(self):
        self.env = read_text(str(ROLE / "templates" / "env.j2"))
        self.tasks = load_yaml_any(str(ROLE / "tasks" / "02_administrator.yml"))
        self.ruby = read_text(
            str(ROLE / "files" / "ruby" / "greenlight" / "ensure_admin.rb")
        )

    def test_the_email_fallback_is_off(self):
        self.assertIn("USE_EMAIL_AS_EXTERNAL_ID_FALLBACK=false\n", sso_block(self.env))
        self.assertNotIn("USE_EMAIL_AS_EXTERNAL_ID_FALLBACK=true", self.env)

    def test_greenlight_keys_users_by_the_sub_claim(self):
        self.assertIn("OPENID_CONNECT_UID_FIELD=sub\n", sso_block(self.env))

    def test_the_admin_subject_comes_from_the_keycloak_directory_helper(self):
        gate = next(task for task in self.tasks if "block" in task)
        self.assertEqual(gate["when"], "BBB_LOGIN_SSO | bool")
        lookup = next(
            task for task in gate["block"] if "ansible.builtin.include_role" in task
        )
        self.assertEqual(
            lookup["ansible.builtin.include_role"],
            {"name": "web-app-keycloak", "tasks_from": "utils/directory_users.yml"},
        )
        self.assertNotIn("application_id", lookup["vars"])

    def test_the_lookup_precedes_the_admin_provisioning(self):
        names = [task["name"] for task in self.tasks]
        lookup = next(i for i, task in enumerate(self.tasks) if "block" in task)
        ensure = names.index("✅ Ensure Greenlight admin (verified, idempotent)")
        self.assertLess(lookup, ensure)

    def test_the_admin_provisioning_receives_the_subject_only_with_sso(self):
        ensure = next(
            task
            for task in self.tasks
            if task["name"].startswith("✅ Ensure Greenlight admin")
        )
        self.assertIn("-e NEW_EXTERNAL_ID", ensure["ansible.builtin.shell"]["cmd"])
        self.assertEqual(
            ensure["environment"]["NEW_EXTERNAL_ID"],
            "{{ (keycloak_directory_users | first).id if (BBB_LOGIN_SSO | bool) else '' }}",
        )

    def test_the_ruby_provisioning_stores_the_subject_as_external_id(self):
        self.assertIn('new_external_id     = ENV.fetch("NEW_EXTERNAL_ID")', self.ruby)
        self.assertIn("user.external_id = new_external_id", self.ruby)
        self.assertIn("unless new_external_id.empty?", self.ruby)


if __name__ == "__main__":
    unittest.main()
