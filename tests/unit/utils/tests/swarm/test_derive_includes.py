from __future__ import annotations

import unittest
import unittest.mock

from utils.tests.swarm import derive_includes as mod


class TestActiveVariantMap(unittest.TestCase):
    def _with_env(self, value):
        return unittest.mock.patch.dict(
            mod.os.environ, {"INFINITO_APP_VARIANTS": value}, clear=False
        )

    def test_absent_env_returns_empty(self):
        with unittest.mock.patch.dict(mod.os.environ, {}, clear=True):
            self.assertEqual(mod._active_variant_map(), {})

    def test_full_map_read(self):
        with self._with_env('{"web-app-x": 1, "web-app-y": 0}'):
            self.assertEqual(
                mod._active_variant_map(), {"web-app-x": 1, "web-app-y": 0}
            )

    def test_malformed_json_returns_empty(self):
        with self._with_env("not-json"):
            self.assertEqual(mod._active_variant_map(), {})

    def test_non_dict_returns_empty(self):
        with self._with_env("[1, 2]"):
            self.assertEqual(mod._active_variant_map(), {})

    def test_non_int_and_bool_indices_dropped(self):
        with self._with_env('{"web-app-x": "1", "web-app-y": true, "web-app-z": 2}'):
            self.assertEqual(mod._active_variant_map(), {"web-app-z": 2})


class TestForceSharedDbView(unittest.TestCase):
    def _keys(self, value):
        return unittest.mock.patch.object(
            mod, "db_provider_service_keys", return_value=value
        )

    def test_flips_shared_on_existing_db_entries(self):
        apps = {
            "web-app-x": {
                "services": {
                    "postgres": {"enabled": True, "shared": False},
                    "sso": {"enabled": False, "shared": False},
                }
            }
        }
        with self._keys({"postgres", "mariadb"}):
            result = mod._force_shared_db_view(apps)
        self.assertTrue(result["web-app-x"]["services"]["postgres"]["shared"])
        self.assertFalse(result["web-app-x"]["services"]["sso"]["shared"])

    def test_missing_entries_are_not_created(self):
        apps = {"web-app-x": {"services": {"sso": {"enabled": True}}}}
        with self._keys({"mariadb"}):
            result = mod._force_shared_db_view(apps)
        self.assertNotIn("mariadb", result["web-app-x"]["services"])

    def test_input_is_not_mutated(self):
        apps = {"web-app-x": {"services": {"mariadb": {"shared": False}}}}
        with self._keys({"mariadb"}):
            mod._force_shared_db_view(apps)
        self.assertFalse(apps["web-app-x"]["services"]["mariadb"]["shared"])

    def test_no_db_keys_returns_input(self):
        apps = {"web-app-x": {"services": {}}}
        with self._keys(set()):
            self.assertIs(mod._force_shared_db_view(apps), apps)


class TestApplicationsForActiveVariants(unittest.TestCase):
    def setUp(self):
        self.base = {
            "web-app-x": {"services": {"sso": {"enabled": "{{ 'k' in group_names }}"}}},
            "web-app-k": {"services": {}},
        }

    def _map(self, value):
        return unittest.mock.patch.object(
            mod, "_active_variant_map", return_value=value
        )

    def test_empty_map_keeps_base(self):
        with self._map({}):
            self.assertIs(
                mod._applications_for_active_variants(self.base),
                self.base,
            )

    def test_variant_zero_is_swapped(self):
        """Variant 0 MAY disable flags the base's dynamic-Jinja form counts
        as enabled (web-app-nextcloud), so index 0 must swap too."""
        v0 = {"services": {"sso": {"enabled": False}}}
        with (
            self._map({"web-app-x": 0}),
            unittest.mock.patch.object(
                mod, "get_variants", return_value={"web-app-x": [v0]}
            ),
        ):
            result = mod._applications_for_active_variants(self.base)
        self.assertEqual(result["web-app-x"], v0)

    def test_all_map_entries_swapped_not_only_primary(self):
        vx = {"services": {"sso": {"enabled": False}}}
        vk = {"services": {"postgres": {"enabled": True}}}
        with (
            self._map({"web-app-x": 1, "web-app-k": 1}),
            unittest.mock.patch.object(
                mod,
                "get_variants",
                return_value={"web-app-x": [{}, vx], "web-app-k": [{}, vk]},
            ),
        ):
            result = mod._applications_for_active_variants(self.base)
        self.assertEqual(result["web-app-x"], vx)
        self.assertEqual(result["web-app-k"], vk)

    def test_out_of_range_entry_keeps_base_others_swap(self):
        vk = {"services": {"postgres": {"enabled": True}}}
        with (
            self._map({"web-app-x": 9, "web-app-k": 1}),
            unittest.mock.patch.object(
                mod,
                "get_variants",
                return_value={"web-app-x": [{}], "web-app-k": [{}, vk]},
            ),
        ):
            result = mod._applications_for_active_variants(self.base)
        self.assertIs(result["web-app-x"], self.base["web-app-x"])
        self.assertEqual(result["web-app-k"], vk)

    def test_unknown_app_in_map_ignored(self):
        with (
            self._map({"web-app-ghost": 1}),
            unittest.mock.patch.object(mod, "get_variants", return_value={}),
        ):
            result = mod._applications_for_active_variants(self.base)
        self.assertEqual(result, self.base)
        self.assertNotIn("web-app-ghost", result)


if __name__ == "__main__":
    unittest.main()
