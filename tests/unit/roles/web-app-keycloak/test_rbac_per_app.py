import os
import importlib.util
import unittest

current_dir = os.path.dirname(__file__)
plugin_path = os.path.abspath(
    os.path.join(
        current_dir,
        "../../../../roles/web-app-keycloak/filter_plugins/rbac_per_app.py",
    )
)
spec = importlib.util.spec_from_file_location("rbac_per_app", plugin_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestKcPerAppMapperName(unittest.TestCase):
    def test_typical_app_id(self):
        self.assertEqual(
            mod.kc_per_app_mapper_name("web-app-wordpress"),
            "ldap-roles-web-app-wordpress",
        )

    def test_svc_db_app_id(self):
        self.assertEqual(
            mod.kc_per_app_mapper_name("svc-db-mariadb"),
            "ldap-roles-svc-db-mariadb",
        )

    def test_empty_string_rejected(self):
        with self.assertRaises(ValueError):
            mod.kc_per_app_mapper_name("")

    def test_non_string_rejected(self):
        with self.assertRaises(ValueError):
            mod.kc_per_app_mapper_name(None)
        with self.assertRaises(ValueError):
            mod.kc_per_app_mapper_name(42)


class TestKcPerAppLdapFilter(unittest.TestCase):
    def test_typical_app_id(self):
        self.assertEqual(
            mod.kc_per_app_ldap_filter("web-app-wordpress"),
            "(&(objectClass=groupOfNames)(cn=web-app-wordpress-*))",
        )

    def test_filter_excludes_other_apps_by_construction(self):
        # The substring filter is anchored at the application id with a
        # trailing hyphen, so a sibling app cannot leak even if its CN
        # starts with the same prefix.
        f = mod.kc_per_app_ldap_filter("web-app-wp")
        self.assertIn("cn=web-app-wp-*", f)
        self.assertNotIn("cn=web-app-wordpress-*", f)

    def test_empty_string_rejected(self):
        with self.assertRaises(ValueError):
            mod.kc_per_app_ldap_filter("")


class TestFilterModuleRegistration(unittest.TestCase):
    def test_filter_module_exposes_both_filters(self):
        fm = mod.FilterModule()
        filters = fm.filters()
        self.assertIn("kc_per_app_mapper_name", filters)
        self.assertIn("kc_per_app_ldap_filter", filters)


if __name__ == "__main__":
    unittest.main()
