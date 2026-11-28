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

    def test_a_pinned_local_db_is_left_unshared(self):
        apps = {
            "web-app-x": {"services": {"postgres": {"enabled": True, "shared": False}}}
        }
        with (
            self._keys({"postgres"}),
            unittest.mock.patch.object(mod, "pinned_local_db", return_value=True),
        ):
            result = mod._force_shared_db_view(apps)
        self.assertFalse(result["web-app-x"]["services"]["postgres"]["shared"])

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


class TestWithoutOptionalCodeploys(unittest.TestCase):
    def test_group_gated_flags_turn_off_and_hard_flags_stay(self):
        apps = {
            "web-app-a": {
                "services": {
                    "postgres": {"enabled": True, "shared": True},
                    "sso": {"enabled": "{{ 'web-app-keycloak' in group_names }}"},
                    "etcd": {
                        "enabled": "{{ lookup('db_instances', 'x').form == 'ha' }}"
                    },
                }
            }
        }
        services = mod._without_optional_codeploys(apps)["web-app-a"]["services"]
        self.assertIs(services["postgres"]["enabled"], True)
        self.assertIs(services["sso"]["enabled"], False)
        self.assertIn("db_instances", services["etcd"]["enabled"])
        self.assertIsInstance(apps["web-app-a"]["services"]["sso"]["enabled"], str)


class TestLabConsumerClosure(unittest.TestCase):
    def test_off_without_the_lab_mode(self):
        with unittest.mock.patch.dict(mod.os.environ, {}, clear=True):
            self.assertEqual(mod.lab_consumer_closure("svc-db-postgres", {}, {}), [])

    def test_variant_scope_leaves_the_consumer_on_its_base_config(self):
        with (
            unittest.mock.patch.object(
                mod,
                "derive_includes",
                return_value=["svc-db-postgres", "svc-dcs-etcd", "web-app-a"],
            ),
            unittest.mock.patch.object(
                mod, "lab_consumer_closure", return_value=["web-app-a", "svc-dcs-etcd"]
            ),
        ):
            self.assertEqual(
                mod.variant_scope("svc-db-postgres"),
                ["svc-db-postgres", "svc-dcs-etcd"],
            )


REGISTRY = {
    "postgres": {"role": "svc-db-postgres"},
    "sso": {"role": "web-app-keycloak"},
}


class TestLightestConsumer(unittest.TestCase):
    def _pick(self, apps, has_suite=lambda role: True):
        with (
            unittest.mock.patch.object(
                mod,
                "applications_if_group_and_all_deps",
                side_effect=lambda applications, roles, **_: list(roles),
            ),
            unittest.mock.patch(
                "pathlib.Path.is_file",
                autospec=True,
                side_effect=lambda path: has_suite(path.parts[-3]),
            ),
        ):
            return mod.lightest_consumer(
                "svc-db-postgres", apps, REGISTRY, blocked=set()
            )

    def test_smallest_own_memory_wins(self):
        apps = {
            "web-app-big": {
                "services": {
                    "postgres": {"enabled": True},
                    "big": {"mem_reservation": "2g"},
                }
            },
            "web-app-small": {
                "services": {
                    "postgres": {"enabled": True},
                    "small": {"mem_reservation": "128m"},
                }
            },
        }
        self.assertEqual(self._pick(apps), "web-app-small")

    def test_provider_containers_do_not_count_against_a_consumer(self):
        apps = {
            "web-app-a": {
                "services": {
                    "postgres": {"enabled": True, "mem_reservation": "8g"},
                    "a": {"mem_reservation": "128m"},
                }
            },
            "web-app-b": {
                "services": {
                    "postgres": {"enabled": True},
                    "b": {"mem_reservation": "512m"},
                }
            },
        }
        self.assertEqual(self._pick(apps), "web-app-a")

    def test_gated_or_untested_consumers_are_skipped(self):
        apps = {
            "web-app-gated": {
                "services": {"postgres": {"enabled": "{{ 'x' in group_names }}"}}
            },
            "web-app-untested": {"services": {"postgres": {"enabled": True}}},
        }
        self.assertIsNone(
            self._pick(apps, has_suite=lambda role: role != "web-app-untested")
        )


if __name__ == "__main__":
    unittest.main()
