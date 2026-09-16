from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.tor_ports import (
    LookupModule,
    collect_exposed_ports,
    collect_onion_ports,
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
            {
                "gitea": {
                    "ports": {
                        "public": {"ssh": 2201},
                        "local": {"http": 8002},
                        "onion": {"ssh": True},
                    }
                }
            },
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

    @staticmethod
    def _apps(**roles: dict) -> dict:
        """The variant-merged applications view for the given roles.

        Every entity keeps its own ``ports``; the top-level ``tor:`` block of
        ``meta/services.yml`` merges in as one more entity alongside them.
        """
        return {role: {"services": dict(entities)} for role, entities in roles.items()}

    def test_only_named_categories_are_forwarded_sorted(self) -> None:
        apps = self._apps(
            **{
                "web-app-gitea": {
                    "gitea": {
                        "ports": {"public": {"ssh": 2201}, "onion": {"ssh": True}}
                    }
                },
                "web-app-mailu": {
                    "mailu": {
                        "ports": {
                            "public": {"smtp": 25, "smtps": 465, "imap": 143},
                            "onion": {"smtp": True},
                        }
                    }
                },
            }
        )

        ports = collect_onion_ports(apps, ["web-app-gitea", "web-app-mailu"])

        self.assertEqual(ports, [25, 2201])

    def test_local_wins_over_public_for_the_same_category(self) -> None:
        """``container_ports`` publishes the local port when the category has
        one, so the forward must target that and not the public alias."""
        apps = self._apps(
            **{
                "web-app-x": {
                    "x": {
                        "ports": {
                            "local": {"http": 8080},
                            "public": {"http": 80},
                            "onion": {"http": True},
                        }
                    }
                }
            }
        )

        self.assertEqual(collect_onion_ports(apps, ["web-app-x"]), [8080])

    def test_a_falsy_or_unrendered_flag_forwards_nothing(self) -> None:
        """The input must be the rendered view: template text left in the flag
        is not quietly read as enabled."""
        apps = self._apps(
            **{
                "web-app-a": {
                    "a": {"ports": {"public": {"ssh": 22}, "onion": {"ssh": False}}}
                },
                "web-app-b": {
                    "b": {
                        "ports": {
                            "public": {"ssh": 23},
                            "onion": {"ssh": "{{ 'svc-net-tor' in group_names }}"},
                        }
                    }
                },
            }
        )

        self.assertEqual(collect_onion_ports(apps, ["web-app-a", "web-app-b"]), [])

    def test_udp_only_categories_are_never_forwarded(self) -> None:
        apps = self._apps(
            **{
                "web-svc-coturn": {
                    "coturn": {
                        "ports": {
                            "public": {
                                "media": 10000,
                                "stun_turn": 3481,
                                "stun_turn_tls": 5351,
                                "ssh": 2299,
                                "relay": {"start": 20000, "end": 39999},
                            },
                            "onion": {
                                "media": True,
                                "relay": True,
                                "stun_turn": True,
                                "stun_turn_tls": True,
                                "ssh": True,
                            },
                        }
                    }
                }
            }
        )

        self.assertEqual(collect_onion_ports(apps, ["web-svc-coturn"]), [2299])

    def test_a_category_with_no_declared_port_is_skipped(self) -> None:
        apps = self._apps(
            **{
                "web-app-x": {
                    "x": {"ports": {"public": {"ssh": 2201}, "onion": {"typo": True}}}
                }
            }
        )

        self.assertEqual(collect_onion_ports(apps, ["web-app-x"]), [])

    def test_a_role_without_an_onion_block_forwards_nothing(self) -> None:
        apps = self._apps(
            **{"web-app-hugo": {"hugo": {"ports": {"local": {"http": 8008}}}}}
        )

        self.assertEqual(collect_onion_ports(apps, ["web-app-hugo"]), [])

    def test_the_port_flag_is_the_gate_not_the_tor_flag(self) -> None:
        """``services.tor.enabled`` is the dependency edge onto svc-net-tor, not
        the port forward; ``ports.onion`` alone decides what gets a
        HiddenServicePort."""
        apps = self._apps(
            **{
                "web-app-gitea": {
                    "tor": {"enabled": False},
                    "gitea": {
                        "ports": {"public": {"ssh": 2201}, "onion": {"ssh": True}}
                    },
                }
            }
        )

        self.assertEqual(collect_onion_ports(apps, ["web-app-gitea"]), [2201])

    def test_role_outside_the_deploy_is_ignored(self) -> None:
        apps = self._apps(
            **{
                "web-app-gitea": {
                    "gitea": {
                        "ports": {"public": {"ssh": 2201}, "onion": {"ssh": True}}
                    }
                }
            }
        )

        self.assertEqual(collect_onion_ports(apps, ["web-app-nope"]), [])

    def test_collect_onion_ports_ignores_non_mappings(self) -> None:
        self.assertEqual(collect_onion_ports({}, ["a"]), [])
        self.assertEqual(collect_onion_ports(None, ["a"]), [])
        apps = {"a": {"services": {"s": {"ports": {"onion": True}}}}}
        self.assertEqual(collect_onion_ports(apps, ["a"]), [])

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

    def test_run_forwards_nothing_without_an_onion_opt_in(self) -> None:
        result = self.lookup.run(
            [],
            variables={"group_names": ["svc-db-openldap", "web-svc-coturn"]},
            roles_dir=str(self.roles_dir),
        )[0]
        self.assertEqual(result, [])

    def test_empty_group_names(self) -> None:
        result = self.lookup.run([], variables={}, roles_dir=str(self.roles_dir))[0]
        self.assertEqual(result, [])

    def test_terms_raise(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lookup.run(["x"], variables={})


if __name__ == "__main__":
    unittest.main()
