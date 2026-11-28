import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.ldap.user_dn import ldap_user_dn
from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

LDAP_TASKS = PROJECT_ROOT / "roles/web-app-fusiondirectory/tasks/01_ldap.yml"
LDAP = {
    "USER": {"ATTRIBUTES": {"ID": "uid"}},
    "DN": {"OU": {"USERS": "ou=users,dc=example,dc=test"}},
}
USERS = {"platform_administrator": {"username": "platformadmin"}}


def _admin_dn_expression():
    return next(
        task["environment"]["FD_ADMIN_DN"]
        for task in load_yaml_any(str(LDAP_TASKS))
        if "FD_ADMIN_DN" in (task.get("environment") or {})
    )


def _render(expression):
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["ldap_user_dn"] = ldap_user_dn
    env.globals["lookup"] = lambda name, key: {"users": USERS}[name][key]
    return env.from_string(expression).render(LDAP=LDAP)


class TestLdapAdminDn(unittest.TestCase):
    def test_the_admin_acl_names_the_entry_by_its_login(self):
        self.assertEqual(
            _render(_admin_dn_expression()),
            "uid=platformadmin,ou=users,dc=example,dc=test",
        )

    def test_the_admin_acl_never_names_the_inventory_key(self):
        expression = _admin_dn_expression()
        self.assertNotIn("=platform_administrator,", expression)
        self.assertNotIn("platform_administrator", _render(expression))


if __name__ == "__main__":
    unittest.main()
