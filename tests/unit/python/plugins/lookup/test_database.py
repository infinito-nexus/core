import importlib.util
import unittest
import unittest.mock as mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables):
        self.available_variables = available_variables


class DatabaseLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_lookup_mod = _load_module(
            "plugins/lookup/database.py", "lookup_database"
        )

    def _make_lookup(self, available_vars: dict):
        lm = self.db_lookup_mod.LookupModule()
        lm._templar = _DummyTemplar(available_vars)
        lm._loader = mock.MagicMock()
        patcher = mock.patch.object(self.db_lookup_mod, "lookup_loader")
        loader_mock = patcher.start()
        self.addCleanup(patcher.stop)
        loader_mock.get.return_value = mock.MagicMock(
            run=lambda _terms, variables=None, **_k: [
                (variables or {}).get("applications", {})
            ]
        )
        return lm

    @staticmethod
    def _fake_get_entity_name(role_name: str) -> str:
        """
        Make entity resolution deterministic for unit tests (no filesystem access).
        Mirrors the typical behavior for your role naming.
        """
        role_name = role_name.strip()
        for prefix in ("web-app-", "web-svc-", "svc-db-", "svc-", "persona-"):
            if role_name.startswith(prefix):
                return role_name[len(prefix) :]
        return role_name

    def test_invalid_terms_raises(self):
        vars_ = {"applications": {}, "ports": {}, "DIR_COMPOSITIONS": "/opt/compose/"}
        lookup = self._make_lookup(vars_)

        with self.assertRaises(AnsibleError):
            lookup.run([], variables=vars_)

        with self.assertRaises(AnsibleError):
            lookup.run(["a", "b", "c"], variables=vars_)

    def test_kwarg_want_is_not_supported_raises(self):
        vars_ = {"applications": {}, "ports": {}, "DIR_COMPOSITIONS": "/opt/compose/"}
        lookup = self._make_lookup(vars_)

        with self.assertRaises(AnsibleError):
            lookup.run(["web-app-foo"], variables=vars_, want="url_full")

    def test_no_dbtype_configured_returns_empty_like_vars_logic(self):
        applications = {
            "web-app-foo": {
                "services": {},
                "secrets": {"credentials": {"database_password": "pw"}},
            }
        }
        ports = {"localhost": {"database": {"svc-db-postgres": "5432"}}}
        vars_ = {
            "applications": applications,
            "ports": ports,
            "DIR_COMPOSITIONS": "/opt/compose/",
        }

        lookup = self._make_lookup(vars_)

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            out = lookup.run(["web-app-foo"], variables=vars_)[0]

        self.assertFalse(out["enabled"])
        self.assertFalse(out["shared"])
        self.assertFalse(out["local"])

        self.assertEqual(out.get("id", ""), "")

        self.assertEqual(out["type"], "")
        self.assertEqual(out["name"], "foo")
        self.assertEqual(out["username"], "foo")
        self.assertEqual(out["host"], "")
        self.assertEqual(out["network"], "")
        self.assertEqual(out["port"], "")
        self.assertEqual(out["env"], "")
        self.assertEqual(out["url_jdbc"], "")
        self.assertEqual(out["url_full"], "")
        self.assertEqual(out["volume"], "")
        self.assertEqual(out["image"], "")
        self.assertEqual(out["version"], "")
        self.assertEqual(out["reach_host"], "127.0.0.1")

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            self.assertEqual(
                lookup.run(["web-app-foo", "url_full"], variables=vars_)[0], ""
            )

    def test_postgres_dedicated_matches_helper_variables_definition(self):
        applications = {
            "web-app-foo": {
                "services": {"postgres": {"enabled": True, "shared": False}},
                "secrets": {"credentials": {"database_password": "pw"}},
            },
            "svc-db-postgres": {
                "services": {
                    "postgres": {
                        "name": "postgres-central",
                        "image": "postgis/postgis",
                        "version": "16",
                        "ports": {"local": {"postgres": "5432"}},
                    }
                }
            },
        }
        ports = {"localhost": {"database": {"svc-db-postgres": "5432"}}}
        vars_ = {
            "applications": applications,
            "ports": ports,
            "DIR_COMPOSITIONS": "/opt/compose/",
        }

        lookup = self._make_lookup(vars_)

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            out = lookup.run(["web-app-foo"], variables=vars_)[0]

        self.assertTrue(out["enabled"])
        self.assertFalse(out["shared"])
        self.assertTrue(out["local"])

        self.assertEqual(out["id"], "svc-db-postgres")

        self.assertEqual(out["type"], "postgres")
        self.assertEqual(out["name"], "foo")
        self.assertEqual(out["username"], "foo")
        self.assertEqual(out["host"], "database")
        self.assertEqual(out["container"], "foo-database")
        self.assertEqual(out["network"], "foo")
        self.assertEqual(out["password"], "pw")
        self.assertEqual(out["port"], "5432")
        self.assertEqual(out["env"], "/opt/compose/foo/.env/postgres.env")
        self.assertEqual(out["initdb_dir"], "/opt/compose/foo/.initdb.d/")
        self.assertEqual(out["build_dir"], "/opt/compose/foo/.postgres-build/")
        self.assertEqual(out["url_jdbc"], "jdbc:postgresql://database:5432/foo")
        self.assertEqual(out["url_full"], "postgres://foo:pw@database:5432/foo")
        self.assertEqual(out["volume"], "foo_database")
        self.assertEqual(out["image"], "postgis/postgis")
        self.assertEqual(out["version"], "16")
        self.assertEqual(out["reach_host"], "127.0.0.1")
        self.assertEqual(out["instance"], "foo")

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            self.assertEqual(
                lookup.run(["web-app-foo", "url_full"], variables=vars_)[0],
                "postgres://foo:pw@database:5432/foo",
            )
            self.assertEqual(
                lookup.run(["web-app-foo", "port"], variables=vars_)[0],
                "5432",
            )

    def test_postgres_shared_uses_central_name_for_host_instance_container_volume(self):
        applications = {
            "web-app-foo": {
                "services": {"postgres": {"enabled": True, "shared": True}},
                "secrets": {"credentials": {"database_password": "pw"}},
            },
            "svc-db-postgres": {
                "services": {
                    "postgres": {
                        "name": "postgres-central",
                        "version": "16",
                        "ports": {"local": {"postgres": "5432"}},
                    }
                }
            },
        }
        ports = {"localhost": {"database": {"svc-db-postgres": "5432"}}}
        vars_ = {
            "applications": applications,
            "ports": ports,
            "DIR_COMPOSITIONS": "/opt/compose/",
        }

        lookup = self._make_lookup(vars_)

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            out = lookup.run(["web-app-foo"], variables=vars_)[0]

        self.assertTrue(out["enabled"])
        self.assertTrue(out["shared"])
        self.assertFalse(out["local"])

        self.assertEqual(out["id"], "svc-db-postgres")

        self.assertEqual(out["host"], "postgres-central")
        self.assertEqual(out["instance"], "postgres-central")

        self.assertEqual(out["container"], "postgres")
        self.assertEqual(out["network"], "postgres")

        self.assertEqual(out["volume"], "postgres-central")

        self.assertEqual(out["url_jdbc"], "jdbc:postgresql://postgres-central:5432/foo")
        self.assertEqual(out["url_full"], "postgres://foo:pw@postgres-central:5432/foo")

    def test_mariadb_jdbc_scheme_stays_mariadb(self):
        applications = {
            "web-app-foo": {
                "services": {"mariadb": {"enabled": True, "shared": False}},
                "secrets": {"credentials": {"database_password": "pw"}},
            },
            "svc-db-mariadb": {
                "services": {
                    "mariadb": {
                        "name": "mariadb-central",
                        "version": "11.4",
                        "ports": {"local": {"mariadb": "3306"}},
                    }
                }
            },
        }
        ports = {"localhost": {"database": {"svc-db-mariadb": "3306"}}}
        vars_ = {
            "applications": applications,
            "ports": ports,
            "DIR_COMPOSITIONS": "/opt/compose/",
        }

        lookup = self._make_lookup(vars_)

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            out = lookup.run(["web-app-foo"], variables=vars_)[0]

        self.assertTrue(out["enabled"])
        self.assertFalse(out["shared"])
        self.assertTrue(out["local"])

        self.assertEqual(out["id"], "svc-db-mariadb")

        self.assertEqual(out["type"], "mariadb")
        self.assertEqual(out["host"], "database")
        self.assertEqual(out["port"], "3306")
        self.assertEqual(out["env"], "/opt/compose/foo/.env/mariadb.env")
        self.assertEqual(out["url_jdbc"], "jdbc:mariadb://database:3306/foo")
        self.assertEqual(out["url_full"], "mariadb://foo:pw@database:3306/foo")

    def test_version_override_on_consumer_wins_over_default(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "shared": False,
                        "version": "15",
                    }
                },
                "secrets": {"credentials": {"database_password": "pw"}},
            },
            "svc-db-postgres": {
                "services": {"postgres": {"name": "postgres-central", "version": "16"}}
            },
        }
        ports = {"localhost": {"database": {"svc-db-postgres": "5432"}}}
        vars_ = {
            "applications": applications,
            "ports": ports,
            "DIR_COMPOSITIONS": "/opt/compose/",
        }

        lookup = self._make_lookup(vars_)

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            out = lookup.run(["web-app-foo"], variables=vars_)[0]

        self.assertTrue(out["enabled"])
        self.assertFalse(out["shared"])

        self.assertEqual(out["id"], "svc-db-postgres")

        self.assertEqual(out["version"], "15")

    def test_local_flag_for_variant_disabling_dedicated_db(self):
        applications = {
            "web-app-foo": {
                "services": {"postgres": {"enabled": False, "shared": False}},
                "secrets": {"credentials": {"database_password": "pw"}},
            }
        }
        ports = {"localhost": {"database": {"svc-db-postgres": "5432"}}}
        vars_ = {
            "applications": applications,
            "ports": ports,
            "DIR_COMPOSITIONS": "/opt/compose/",
        }

        lookup = self._make_lookup(vars_)

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            out = lookup.run(["web-app-foo"], variables=vars_)[0]

        self.assertFalse(out["enabled"])
        self.assertFalse(out["shared"])
        self.assertFalse(out["local"])
        self.assertEqual(out["host"], "")

        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            self.assertFalse(lookup.run(["web-app-foo", "local"], variables=vars_)[0])

    def test_multiple_database_services_raise(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "mariadb": {"enabled": True, "shared": False},
                    "postgres": {"enabled": True, "shared": False},
                }
            }
        }
        vars_ = {
            "applications": applications,
            "ports": {"localhost": {"database": {}}},
            "DIR_COMPOSITIONS": "/opt/compose/",
        }

        lookup = self._make_lookup(vars_)

        with self.assertRaises(AnsibleError):
            lookup.run(["web-app-foo"], variables=vars_)

    def test_a_dedicated_engine_keeps_the_name_its_role_declares(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "shared": False,
                        "name": "foo-postgres-1",
                    }
                },
                "secrets": {"credentials": {"database_password": "pw"}},
            },
            "svc-db-postgres": {
                "services": {
                    "postgres": {"version": "16", "ports": {"local": {"postgres": ""}}}
                }
            },
        }
        vars_ = {
            "applications": applications,
            "ports": {"localhost": {"database": {"svc-db-postgres": "5432"}}},
            "DIR_COMPOSITIONS": "/opt/compose/",
        }
        self.assertEqual(self._resolve(vars_)["container"], "foo-postgres-1")

    def _mode_vars(self, shared, **extra):
        applications = {
            "web-app-foo": {
                "services": {"postgres": {"enabled": True, "shared": shared}},
                "secrets": {"credentials": {"database_password": "pw"}},
            },
            "svc-db-postgres": {
                "services": {
                    "postgres": {
                        "name": "postgres",
                        "version": "16",
                        "ports": {"local": {"postgres": ""}},
                    }
                }
            },
        }
        return {
            "applications": applications,
            "ports": {"localhost": {"database": {"svc-db-postgres": "5432"}}},
            "DIR_COMPOSITIONS": "/opt/compose/",
            **extra,
        }

    def _dedicated_vars(self, **extra):
        return self._mode_vars(False, **extra)

    def _resolve(self, vars_):
        lookup = self._make_lookup(vars_)
        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            return lookup.run(["web-app-foo"], variables=vars_)[0]

    def test_swarm_names_the_service_after_the_stack(self):
        out = self._resolve(self._dedicated_vars(DEPLOYMENT_MODE="swarm"))
        self.assertEqual(out["service_name"], "foo_database")
        self.assertIn("resolve-container-id", out["address"])

    def test_compose_mode_force_beats_the_cluster_mode(self):
        out = self._resolve(
            self._dedicated_vars(DEPLOYMENT_MODE="swarm", compose_mode_force="compose")
        )
        self.assertEqual(out["service_name"], "database")
        self.assertEqual(out["address"], out["container"])

    def test_an_empty_force_falls_back_to_the_cluster_mode(self):
        out = self._resolve(
            self._dedicated_vars(DEPLOYMENT_MODE="swarm", compose_mode_force="")
        )
        self.assertEqual(out["service_name"], "foo_database")

    def test_a_consumers_force_does_not_reach_the_central_engine(self):
        out = self._resolve(
            self._mode_vars(True, DEPLOYMENT_MODE="swarm", compose_mode_force="compose")
        )
        self.assertEqual(out["service_name"], "postgres_postgres")


if __name__ == "__main__":
    unittest.main()
