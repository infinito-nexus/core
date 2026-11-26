"""Greenlight links an SSO login by the Keycloak subject, never by e-mail."""

from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "web-app-bigbluebutton"
SSO_START = "{% if BBB_LOGIN_SSO | bool %}"


def sso_env(enabled: bool) -> dict[str, str]:
    """
    Args:
        enabled: value of ``BBB_LOGIN_SSO``.

    Returns:
        The ``KEY=VALUE`` pairs the SSO block of env.j2 renders.
    """
    lines = read_text(str(ROLE / "templates" / "env.j2")).splitlines()
    start = lines.index(SSO_START)
    end = lines.index("{% endif %}", start)
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = bool
    rendered = environment.from_string("\n".join(lines[start : end + 1])).render(
        BBB_LOGIN_SSO=enabled,
        OIDC={
            "CLIENT": {
                "ID": "bigbluebutton",
                "SECRET": "",
                "ISSUER_URL": "https://auth.example.org/realms/main",
            }
        },
        application_id="web-app-bigbluebutton",
        lookup=lambda *_terms: "https://meet.example.org/",
    )
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


class GreenlightSubjectLinkTests(unittest.TestCase):
    def setUp(self):
        self.tasks = load_yaml_any(str(ROLE / "tasks" / "02_administrator.yml"))

    def test_the_email_fallback_is_off(self):
        self.assertEqual(sso_env(True)["USE_EMAIL_AS_EXTERNAL_ID_FALLBACK"], "false")
        self.assertEqual(sso_env(False), {})

    def test_greenlight_keys_users_by_the_sub_claim(self):
        self.assertEqual(sso_env(True)["OPENID_CONNECT_UID_FIELD"], "sub")

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


if __name__ == "__main__":
    unittest.main()
