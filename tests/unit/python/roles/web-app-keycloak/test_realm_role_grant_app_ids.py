import unittest

from jinja2 import Environment, StrictUndefined

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

EXPRESSION = load_yaml_any(
    str(PROJECT_ROOT / "roles/web-app-keycloak" / ROLE_FILE_VARS_MAIN)
)["KEYCLOAK_REALM_ROLE_GRANT_APP_IDS"]


def render(ldap_enabled):
    env = Environment(undefined=StrictUndefined)
    env.filters["bool"] = bool
    return env.from_string(EXPRESSION).render(
        KEYCLOAK_LDAP_ENABLED=ldap_enabled,
        KEYCLOAK_RBAC_RUN_APP_IDS=["web-app-opencloud", "web-app-nextcloud"],
        KEYCLOAK_RBAC_ALL_APP_IDS=["web-app-nextcloud"],
    )


class TestRealmRoleGrantAppIds(unittest.TestCase):
    def test_with_ldap_only_the_apps_this_host_wrote_groups_for(self):
        self.assertEqual(render(True), "['web-app-nextcloud']")

    def test_without_ldap_every_app_of_the_run(self):
        self.assertEqual(render(False), "['web-app-opencloud', 'web-app-nextcloud']")


if __name__ == "__main__":
    unittest.main()
