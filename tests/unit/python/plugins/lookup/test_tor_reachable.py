from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.tor_reachable import LookupModule, is_reachable
from utils.cache import _reset_cache_for_tests
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _apps(tor_enabled: object, exposed: object) -> dict:
    return {
        "svc-db-mariadb": {
            "services": {
                "tor": {"enabled": tor_enabled},
                "mariadb": {"exposed": exposed, "ports": {"local": {"mariadb": 3306}}},
            }
        }
    }


class TestIsReachable(unittest.TestCase):
    def test_tor_enabled_and_exposed(self) -> None:
        self.assertTrue(is_reachable(_apps(True, True), "svc-db-mariadb"))

    def test_exposed_without_tor(self) -> None:
        self.assertFalse(is_reachable(_apps(False, True), "svc-db-mariadb"))

    def test_tor_without_exposed(self) -> None:
        self.assertFalse(is_reachable(_apps(True, False), "svc-db-mariadb"))

    def test_string_truthiness_matches_tor_ports(self) -> None:
        self.assertTrue(is_reachable(_apps("true", "yes"), "svc-db-mariadb"))
        self.assertFalse(is_reachable(_apps("true", "off"), "svc-db-mariadb"))

    def test_exposed_service_without_local_port_has_no_onion_target(self) -> None:
        apps = {
            "svc-db-mariadb": {
                "services": {
                    "tor": {"enabled": True},
                    "mariadb": {"exposed": True, "ports": {"public": {"tls": 3307}}},
                }
            }
        }
        self.assertFalse(is_reachable(apps, "svc-db-mariadb"))

    def test_unknown_or_malformed_application(self) -> None:
        self.assertFalse(is_reachable(_apps(True, True), "svc-db-nope"))
        self.assertFalse(is_reachable({"a": None}, "a"))
        self.assertFalse(is_reachable({}, "a"))


class TestTorReachableLookup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmpdir.name) / "roles"
        _reset_cache_for_tests()
        for role, exposed in (("svc-db-mariadb", True), ("svc-db-postgres", False)):
            path = self.roles_dir / role / ROLE_FILE_META_SERVICES
            path.parent.mkdir(parents=True, exist_ok=True)
            entity = role.rsplit("-", 1)[-1]
            path.write_text(
                dump_yaml_str(
                    {
                        "tor": {"enabled": True},
                        entity: {
                            "exposed": exposed,
                            "ports": {"local": {entity: 3306}},
                        },
                    }
                ),
                encoding="utf-8",
            )
        self.lookup = LookupModule()
        self.lookup._templar = None

    def tearDown(self) -> None:
        _reset_cache_for_tests()
        self._tmpdir.cleanup()

    def _run(self, application_id: str) -> bool:
        return self.lookup.run(
            [application_id], variables={}, roles_dir=str(self.roles_dir)
        )[0]

    def test_run_resolves_against_the_merged_applications_view(self) -> None:
        self.assertTrue(self._run("svc-db-mariadb"))
        self.assertFalse(self._run("svc-db-postgres"))

    def test_arity_and_empty_term_raise(self) -> None:
        for terms in ([], ["a", "b"], [""], ["   "]):
            with self.subTest(terms=terms), self.assertRaises(AnsibleError):
                self.lookup.run(terms, variables={}, roles_dir=str(self.roles_dir))


if __name__ == "__main__":
    unittest.main()
