# tests/unit/plugins/lookup/test_database.py
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleError


def _repo_root() -> Path:
    # __file__ = tests/unit/plugins/lookup/test_database.py
    return Path(__file__).resolve().parents[4]


def _load_module(rel_path: str, name: str):
    path = _repo_root() / rel_path
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
        # LookupBase expects _templar to exist (we only use available_variables)
        lm._templar = _DummyTemplar(available_vars)
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
            lookup.run([], variables=vars_)  # missing consumer_id

        with self.assertRaises(AnsibleError):
            lookup.run(["a", "b", "c"], variables=vars_)  # too many terms

    def test_kwarg_want_is_not_supported_raises(self):
        vars_ = {"applications": {}, "ports": {}, "DIR_COMPOSITIONS": "/opt/compose/"}
        lookup = self._make_lookup(vars_)

        with self.assertRaises(AnsibleError):
            lookup.run(["web-app-foo"], variables=vars_, want="url_full")

    def test_no_dbtype_configured_returns_empty_like_vars_logic(self):
        applications = {
            "web-app-foo": {
                "services": {},
                "credentials": {"database_password": "pw"},
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

        # enabled/shared are surfaced even if type is empty
        self.assertFalse(out["enabled"])
        self.assertFalse(out["shared"])

        # id should be empty when dbtype is empty
        self.assertEqual(out.get("id", ""), "")

        # Mirrors the "if _dbtype else '' / False" branches from your vars
        self.assertEqual(out["type"], "")
        self.assertEqual(out["name"], "foo")
        self.assertEqual(out["username"], "foo")
        self.assertEqual(out["host"], "")
        self.assertEqual(out["port"], "")
        self.assertEqual(out["env"], "")
        self.assertEqual(out["url_jdbc"], "")
        self.assertEqual(out["url_full"], "")
        self.assertEqual(out["volume"], "")
        self.assertEqual(out["image"], "")
        self.assertEqual(out["version"], "")
        self.assertEqual(out["reach_host"], "127.0.0.1")

        # STRICT projection API (positional want-path)
        with patch.object(
            self.db_lookup_mod,
            "get_entity_name",
            side_effect=self._fake_get_entity_name,
        ):
            self.assertEqual(
                lookup.run(["web-app-foo", "url_full"], variables=vars_)[0], ""
            )

    def test_postgres_dedicated_matches_helper_variables_definition(self):
        # Consumer config: postgres enabled locally (shared=false).
        # Per req-009 the database port is hung on the database role's own
        # services.<type>.ports.local.database entry.
        applications = {
            "web-app-foo": {
                "services": {"postgres": {"enabled": True, "shared": False}},
                "credentials": {"database_password": "pw"},
            },
            # Central DB role config (used only for defaults like version; name not used if shared=false)
            "svc-db-postgres": {
                "services": {
                    "postgres": {
                        "name": "postgres-central",
                        "version": "16",
                        "ports": {"local": {"database": "5432"}},
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

        # enabled/shared surfaced
        self.assertTrue(out["enabled"])
        self.assertFalse(out["shared"])

        # id should be present
        self.assertEqual(out["id"], "svc-db-postgres")

        # ---- Helper-variable equivalence checks (no database_ prefix in lookup output) ----
        self.assertEqual(out["type"], "postgres")
        self.assertEqual(out["name"], "foo")
        self.assertEqual(out["username"], "foo")
        self.assertEqual(out["host"], "database")
        self.assertEqual(out["container"], "foo-database")
        self.assertEqual(out["password"], "pw")
        self.assertEqual(out["port"], "5432")
        self.assertEqual(out["env"], "/opt/compose/foo/.env/postgres.env")
        self.assertEqual(out["url_jdbc"], "jdbc:postgresql://database:5432/foo")
        self.assertEqual(out["url_full"], "postgres://foo:pw@database:5432/foo")
        self.assertEqual(out["volume"], "foo_database")
        self.assertEqual(out["image"], "postgres")
        self.assertEqual(out["version"], "16")
        self.assertEqual(out["reach_host"], "127.0.0.1")
        self.assertEqual(out["instance"], "foo")

        # STRICT projection API (positional want-path)
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
                "credentials": {"database_password": "pw"},
            },
            "svc-db-postgres": {
                "services": {
                    "postgres": {
                        "name": "postgres-central",
                        "version": "16",
                        "ports": {"local": {"database": "5432"}},
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

        # enabled/shared surfaced
        self.assertTrue(out["enabled"])
        self.assertTrue(out["shared"])

        # id should be present
        self.assertEqual(out["id"], "svc-db-postgres")

        # database_host/database_instance = central name
        self.assertEqual(out["host"], "postgres-central")
        self.assertEqual(out["instance"], "postgres-central")

        # database_container = _dbtype when central_enabled
        self.assertEqual(out["container"], "postgres")

        # database_volume: no "<entity>_" prefix when shared, just host
        self.assertEqual(out["volume"], "postgres-central")

        # URLs use central host
        self.assertEqual(out["url_jdbc"], "jdbc:postgresql://postgres-central:5432/foo")
        self.assertEqual(out["url_full"], "postgres://foo:pw@postgres-central:5432/foo")

    def test_mariadb_jdbc_scheme_stays_mariadb(self):
        applications = {
            "web-app-foo": {
                "services": {"mariadb": {"enabled": True, "shared": False}},
                "credentials": {"database_password": "pw"},
            },
            "svc-db-mariadb": {
                "services": {
                    "mariadb": {
                        "name": "mariadb-central",
                        "version": "11.4",
                        "ports": {"local": {"database": "3306"}},
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

        # id should be present
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
                "credentials": {"database_password": "pw"},
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

        # enabled/shared surfaced
        self.assertTrue(out["enabled"])
        self.assertFalse(out["shared"])

        # id should be present
        self.assertEqual(out["id"], "svc-db-postgres")

        # consumer override should win:
        self.assertEqual(out["version"], "15")

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


if __name__ == "__main__":
    unittest.main()
