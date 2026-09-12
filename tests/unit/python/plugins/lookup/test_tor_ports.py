from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.tor_ports import (
    LookupModule,
    collect_exposed_ports,
    collect_public_ports,
)
from utils.cache import _reset_cache_for_tests
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _write_services(roles_dir: Path, role: str, payload: dict) -> None:
    payload = dict(payload)
    payload.setdefault("tor", {"enabled": True})
    path = roles_dir / role / ROLE_FILE_META_SERVICES
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml_str(payload), encoding="utf-8")


class TestTorPortsLookup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmpdir.name) / "roles"
        self.roles_dir.mkdir(parents=True)
        _reset_cache_for_tests()
        _write_services(
            self.roles_dir,
            "web-app-gitea",
            {"gitea": {"ports": {"public": {"ssh": 2201}, "local": {"http": 8002}}}},
        )
        _write_services(
            self.roles_dir,
            "svc-db-openldap",
            {"openldap": {"ports": {"public": {"ldaps": 636}, "local": {"ldap": 389}}}},
        )
        _write_services(
            self.roles_dir,
            "web-svc-coturn",
            {
                "coturn": {
                    "ports": {
                        "public": {
                            "stun_turn": 3481,
                            "stun_turn_tls": 5351,
                            "relay": {"start": 20000, "end": 39999},
                        },
                        "local": {"http": 8064},
                    }
                }
            },
        )
        _write_services(
            self.roles_dir,
            "web-app-hugo",
            {"hugo": {"ports": {"local": {"http": 8008}}}},
        )
        self.lookup = LookupModule()
        self.lookup._templar = None

    def tearDown(self) -> None:
        _reset_cache_for_tests()
        self._tmpdir.cleanup()

    def test_collects_public_single_ints_sorted(self) -> None:
        ports = collect_public_ports(
            ["web-app-gitea", "svc-db-openldap"], self.roles_dir
        )
        self.assertEqual(ports, [636, 2201])

    def test_relay_ranges_excluded(self) -> None:
        ports = collect_public_ports(["web-svc-coturn"], self.roles_dir)
        self.assertEqual(ports, [3481, 5351])

    def test_media_category_excluded(self) -> None:
        _write_services(
            self.roles_dir,
            "web-app-jitsi",
            {"jitsi": {"ports": {"public": {"media": 10000}, "local": {"http": 8084}}}},
        )
        self.assertEqual(collect_public_ports(["web-app-jitsi"], self.roles_dir), [])

    def test_roles_without_public_ports_yield_nothing(self) -> None:
        self.assertEqual(collect_public_ports(["web-app-hugo"], self.roles_dir), [])

    def test_tor_disabled_role_excluded(self) -> None:
        _write_services(
            self.roles_dir,
            "web-app-optout",
            {
                "optout": {"ports": {"public": {"ssh": 2299}}},
                "tor": {"enabled": False},
            },
        )
        self.assertEqual(collect_public_ports(["web-app-optout"], self.roles_dir), [])

    def test_unknown_role_ignored(self) -> None:
        self.assertEqual(collect_public_ports(["web-app-nope"], self.roles_dir), [])

    def test_collect_exposed_ports_gated_and_deployed(self) -> None:
        apps = {
            "svc-db-postgres": {
                "services": {
                    "postgres": {
                        "exposed": True,
                        "ports": {"local": {"postgres": 5432}},
                    }
                }
            },
            "svc-db-mariadb": {
                "services": {
                    "mariadb": {"exposed": False, "ports": {"local": {"mariadb": 3306}}}
                }
            },
            "svc-db-openldap": {
                "services": {
                    "openldap": {
                        "exposed": True,
                        "ports": {"local": {"ldap": 389}, "public": {"ldaps": 636}},
                    }
                }
            },
            "web-app-x": {
                "services": {
                    "x": {"exposed": True, "ports": {"public": {"http": 8080}}}
                }
            },
        }
        ports = collect_exposed_ports(
            apps, ["svc-db-postgres", "svc-db-openldap", "svc-db-mariadb"]
        )
        self.assertEqual(ports, [389, 5432])

    def test_exposed_public_forwards_the_public_group(self) -> None:
        """The active mail provider's protocol ports ride the node onion."""
        apps = {
            "web-app-stalwart": {
                "services": {
                    "stalwart": {
                        "exposed": "public",
                        "ports": {
                            "local": {"http": 8081},
                            "public": {"smtp": 25, "smtps": 465, "imaps": 993},
                        },
                    }
                }
            }
        }
        self.assertEqual(
            collect_exposed_ports(apps, ["web-app-stalwart"]), [25, 465, 993]
        )

    def test_exposed_public_does_not_leak_the_local_group(self) -> None:
        """`public` replaces `local` — the reverse-proxied http port stays off the onion port list."""
        apps = {
            "a": {
                "services": {
                    "s": {
                        "exposed": "public",
                        "ports": {"local": {"http": 8081}, "public": {"smtps": 465}},
                    }
                }
            }
        }
        self.assertEqual(collect_exposed_ports(apps, ["a"]), [465])

    def test_exposed_true_still_never_forwards_public_ports(self) -> None:
        """openldap's ldaps 636 must stay a non-forward: nothing listens on it in the exposed variant."""
        apps = {
            "svc-db-openldap": {
                "services": {
                    "openldap": {
                        "exposed": True,
                        "ports": {"local": {"ldap": 389}, "public": {"ldaps": 636}},
                    }
                }
            }
        }
        self.assertEqual(collect_exposed_ports(apps, ["svc-db-openldap"]), [389])

    def test_exposed_unknown_string_forwards_nothing(self) -> None:
        apps = {
            "a": {
                "services": {
                    "s": {"exposed": "everything", "ports": {"public": {"smtp": 25}}}
                }
            }
        }
        self.assertEqual(collect_exposed_ports(apps, ["a"]), [])

    def test_collect_exposed_ports_ignores_non_mappings(self) -> None:
        self.assertEqual(collect_exposed_ports({}, ["a"]), [])
        self.assertEqual(collect_exposed_ports(None, ["a"]), [])
        apps = {"a": {"services": {"s": {"exposed": True, "ports": None}}}}
        self.assertEqual(collect_exposed_ports(apps, ["a"]), [])

    def test_run_returns_hidden_service_mappings(self) -> None:
        result = self.lookup.run(
            [],
            variables={"group_names": ["web-app-gitea", "web-app-hugo"]},
            roles_dir=str(self.roles_dir),
        )[0]
        self.assertEqual(result, [{"onion_port": 2201, "target": "127.0.0.1:2201"}])

    def test_empty_group_names(self) -> None:
        result = self.lookup.run([], variables={}, roles_dir=str(self.roles_dir))[0]
        self.assertEqual(result, [])

    def test_terms_raise(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lookup.run(["x"], variables={})


if __name__ == "__main__":
    unittest.main()
