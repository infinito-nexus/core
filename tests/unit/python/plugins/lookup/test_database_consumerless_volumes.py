"""Unit tests for ``plugins/lookup/database_consumerless_volumes.py``.

Pins the consumer predicate: a deployed role consumes a provider when it
enables a shared database of that provider's engine. A dedicated database, a
provider itself, or a consumer of the other engine never counts.
"""

import importlib.util
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _database(engine: str, *, shared: bool = True) -> dict:
    return {"services": {engine: {"enabled": True, "shared": shared}}}


class DatabaseConsumerlessVolumesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            "plugins/lookup/database_consumerless_volumes.py",
            "lookup_database_consumerless_volumes",
        )

    def setUp(self):
        self._original_loader = self.mod.lookup_loader
        self._applications: dict = {}

        def _get(name, **_kwargs):
            if name == "applications":
                return mock.MagicMock(run=lambda *_a, **_k: [self._applications])
            return mock.MagicMock(run=self._volume_run)

        loader_mock = mock.MagicMock()
        loader_mock.get.side_effect = _get
        self.mod.lookup_loader = loader_mock

    def tearDown(self):
        self.mod.lookup_loader = self._original_loader

    @staticmethod
    def _volume_run(terms, **_kwargs):
        provider, semantic = terms
        return [{"name": f"{provider.removeprefix('svc-db-')}_{semantic}"}]

    def _run(self, group_names, applications, terms=()):
        self._applications = applications
        lk = self.mod.LookupModule()
        lk._loader = mock.MagicMock()
        lk._templar = mock.MagicMock()
        return lk.run(list(terms), variables={"group_names": list(group_names)})

    def test_terms_are_refused(self):
        with self.assertRaises(AnsibleError):
            self._run([], {}, terms=("postgres",))

    def test_a_provider_without_a_consumer_is_named(self):
        result = self._run(
            ["svc-db-postgres", "web-svc-mirror"],
            {"svc-db-postgres": _database("postgres")},
        )
        self.assertEqual(result, [["postgres_data"]])

    def test_a_shared_consumer_claims_its_provider(self):
        result = self._run(
            ["svc-db-postgres", "web-app-matomo"],
            {"web-app-matomo": _database("postgres")},
        )
        self.assertEqual(result, [[]])

    def test_a_dedicated_database_claims_no_provider(self):
        result = self._run(
            ["svc-db-postgres", "web-app-a"],
            {"web-app-a": _database("postgres", shared=False)},
        )
        self.assertEqual(result, [["postgres_data"]])

    def test_a_consumer_claims_only_its_own_engine(self):
        result = self._run(
            ["svc-db-mariadb", "svc-db-postgres", "web-app-matomo"],
            {"web-app-matomo": _database("mariadb")},
        )
        self.assertEqual(result, [["postgres_data"]])

    def test_a_provider_that_is_not_deployed_is_not_named(self):
        self.assertEqual(self._run(["web-app-a"], {}), [[]])

    def test_a_role_with_two_database_services_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run(
                ["svc-db-postgres", "web-app-a"],
                {
                    "web-app-a": {
                        "services": {
                            "mariadb": {"enabled": True, "shared": True},
                            "postgres": {"enabled": True, "shared": True},
                        }
                    }
                },
            )


if __name__ == "__main__":
    unittest.main()
