import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

current_dir = str(Path(__file__).parent)
plugin_path = str(
    Path(
        str(
            Path(current_dir)
            / "../../../../roles/web-app-keycloak/filter_plugins/rbac_per_app.py"
        )
    ).resolve()
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


class TestRbacAppIds(unittest.TestCase):
    @patch.object(mod, "list_invokable_app_ids")
    def test_filters_to_invokable_apps(self, mock_invokable):
        mock_invokable.return_value = [
            "web-app-friendica",
            "svc-db-postgres",
            "web-app-baserow",
        ]
        group_names = [
            "web-app-friendica",
            "svc-db-postgres",
            "not-a-deployed-app",
        ]
        self.assertEqual(
            mod.rbac_app_ids(group_names),
            ["svc-db-postgres", "web-app-friendica"],
        )

    @patch.object(mod, "list_invokable_app_ids")
    def test_deduplicates(self, mock_invokable):
        mock_invokable.return_value = ["a", "b"]
        self.assertEqual(
            mod.rbac_app_ids(["a", "a", "b", "b"]),
            ["a", "b"],
        )

    @patch.object(mod, "list_invokable_app_ids")
    def test_sorted(self, mock_invokable):
        mock_invokable.return_value = ["a", "b", "c"]
        self.assertEqual(
            mod.rbac_app_ids(["c", "a", "b"]),
            ["a", "b", "c"],
        )

    @patch.object(mod, "list_invokable_app_ids")
    def test_none_app_ids_treated_as_empty(self, mock_invokable):
        mock_invokable.return_value = ["a"]
        self.assertEqual(mod.rbac_app_ids(None), [])

    @patch.object(mod, "list_invokable_app_ids")
    def test_empty_app_ids_returns_empty(self, mock_invokable):
        mock_invokable.return_value = ["a", "b"]
        self.assertEqual(mod.rbac_app_ids([]), [])

    def test_invalid_app_ids_type(self):
        with self.assertRaises(TypeError):
            mod.rbac_app_ids("not-a-list")


class TestFilterModuleRegistration(unittest.TestCase):
    def test_filter_module_exposes_all_filters(self):
        fm = mod.FilterModule()
        filters = fm.filters()
        self.assertIn("kc_per_app_mapper_name", filters)
        self.assertIn("kc_per_app_ldap_filter", filters)
        self.assertIn("rbac_app_ids", filters)


if __name__ == "__main__":
    unittest.main()
