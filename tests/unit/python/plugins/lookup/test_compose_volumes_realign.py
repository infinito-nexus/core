"""Unit tests for the mariadb credential realignment.

Pins the two properties the realignment depends on and neither the lint
suite nor the other compose_volumes tests reach: the SQL must stay a no-op
during the entrypoint's first-start server, and the config entry must only
appear for an engine the app owns alone.
"""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock
from typing import ClassVar

import jinja2

from utils.cache.files import read_text

from . import PROJECT_ROOT

_TEMPLATE = PROJECT_ROOT / "roles/sys-svc-rdbms/templates/sql/mariadb-realign.sql.j2"


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_compose_volumes_realign",
        str(PROJECT_ROOT / "plugins/lookup/compose_volumes.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _render(**answers) -> str:
    values = {"username": "appuser", "password": "s3cret", "name": "appdb"}
    values.update(answers)

    def _lookup(_plugin, _app, key):
        return values[key]

    env = jinja2.Environment(autoescape=False)  # noqa: S701 - renders SQL, HTML escaping would corrupt the literals
    return env.from_string(read_text(str(_TEMPLATE))).render(
        lookup=_lookup, application_id="web-app-x"
    )


class TestRealignSql(unittest.TestCase):
    def test_it_alters_the_application_user_with_the_current_password(self) -> None:
        sql = _render()
        self.assertIn("ALTER USER IF EXISTS 'appuser'@'%'", sql)
        self.assertIn("IDENTIFIED BY 's3cret'", sql)

    def test_if_exists_keeps_it_a_noop_on_the_entrypoint_s_first_start(self) -> None:
        """Without the guard the entrypoint's own CREATE USER dies under set -e."""
        self.assertIn("ALTER USER IF EXISTS", _render())
        self.assertNotIn("CREATE USER", _render())

    def test_it_never_touches_root(self) -> None:
        """Giving root a password breaks the first-start readiness probe."""
        self.assertNotIn("root", _render())

    def test_it_grants_nothing(self) -> None:
        """Rotating a credential changes passwords, not privileges."""
        self.assertNotIn("GRANT", _render())

    def test_it_stays_a_single_statement(self) -> None:
        self.assertEqual(1, _render().count(";"))


class TestWithDatabaseRealign(unittest.TestCase):
    module: ClassVar = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_lookup()

    def _call(self, service_key, service_cfg, source="/srv/x/.env/mariadb-realign.sql"):
        lm = self.module.LookupModule()
        lm._loader = None
        lm._templar = None
        resolve = mock.patch.object(
            self.module,
            "resolve_database_service_key",
            side_effect=service_key
            if isinstance(service_key, Exception)
            else lambda *_a: service_key,
        )
        config = mock.patch.object(
            self.module,
            "get_database_service_config",
            return_value=service_cfg,
        )
        with (
            resolve,
            config,
            mock.patch.object(self.module, "lookup_loader") as loader_mock,
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [source]
            )
            return lm._with_database_realign({}, "web-app-x", {}, None)

    def test_a_dedicated_mariadb_gets_the_config_entry(self) -> None:
        result = self._call("mariadb", {})
        self.assertIn(self.module.REALIGN_CONFIG_KEY, result)
        entry = result[self.module.REALIGN_CONFIG_KEY]
        self.assertEqual("/srv/x/.env/mariadb-realign.sql", entry["file"])
        self.assertTrue(entry["name"].startswith("x_database_realign_"))

    def test_postgres_gets_nothing(self) -> None:
        self.assertIsNone(self._call("postgres", {}))

    def test_a_shared_engine_gets_nothing(self) -> None:
        self.assertIsNone(self._call("mariadb", {"shared": True}))

    def test_an_unrendered_source_gets_nothing(self) -> None:
        self.assertIsNone(self._call("mariadb", {}, source=""))

    def test_two_engines_defer_to_the_caller_s_diagnostic(self) -> None:
        """Raising here hides compose_volumes' message naming the collision."""
        self.assertIsNone(self._call(ValueError("web-app-x: two engines"), {}))


if __name__ == "__main__":
    unittest.main()
