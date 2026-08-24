from __future__ import annotations

import unittest

from utils.roles.applications.services import resources as cli


class TestCollectRoleResources(unittest.TestCase):
    def _fake_registry(self) -> dict:
        return {
            "oidc": {"role": "web-app-keycloak"},
            "email": {"role": "web-app-mailu"},
            "postgres": {"role": "svc-db-postgres"},
        }

    def _fake_applications(self) -> dict:
        return {
            "web-app-peertube": {
                "services": {
                    "peertube": {
                        "cpus": 4,
                        "mem_reservation": "4g",
                        "mem_limit": "8g",
                        "pids_limit": 2048,
                    },
                    "redis": {
                        "enabled": True,
                        "cpus": "0.5",
                        "mem_reservation": "256m",
                        "mem_limit": "512m",
                        "pids_limit": 512,
                    },
                    "oidc": {"enabled": True, "shared": True},
                    "postgres": {"enabled": True, "shared": True},
                    "email": {"enabled": True, "shared": True},
                    "css": {"enabled": False, "shared": True},
                }
            },
            "web-app-keycloak": {
                "services": {
                    "keycloak": {
                        "cpus": "2.0",
                        "mem_reservation": "2g",
                        "mem_limit": "4g",
                        "pids_limit": 1024,
                    },
                }
            },
            "web-app-mailu": {
                "services": {
                    "mailu": {},
                    "oidc": {"enabled": True, "shared": True},
                }
            },
            "svc-db-postgres": {
                "services": {
                    "postgres": {
                        "cpus": 2,
                        "mem_reservation": "4g",
                        "mem_limit": "6g",
                        "pids_limit": 1024,
                    }
                }
            },
        }

    def test_primary_and_sidecar_grouped_then_shared_deps(self) -> None:
        rows: list = []
        warnings: list = []
        cli.collect_role_resources(
            role_name="web-app-peertube",
            applications=self._fake_applications(),
            service_registry=self._fake_registry(),
            visited=set(),
            rows=rows,
            warnings=warnings,
        )
        labels = [(r["role"], r["service"]) for r in rows]
        self.assertEqual(labels[0], ("web-app-peertube", "peertube"))
        self.assertEqual(labels[1], ("web-app-peertube", "redis"))
        self.assertIn(("web-app-keycloak", "keycloak"), labels)
        self.assertIn(("svc-db-postgres", "postgres"), labels)
        self.assertIn(("web-app-mailu", "mailu"), labels)
        peertube_pos = labels.index(("web-app-peertube", "redis"))
        keycloak_pos = labels.index(("web-app-keycloak", "keycloak"))
        self.assertLess(peertube_pos, keycloak_pos)

    def test_disabled_services_are_skipped(self) -> None:
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-peertube",
            applications=self._fake_applications(),
            service_registry=self._fake_registry(),
            visited=set(),
            rows=rows,
            warnings=[],
        )
        labels = {(r["role"], r["service"]) for r in rows}
        self.assertNotIn(("web-app-peertube", "css"), labels)

    def test_cycle_protection_visits_each_role_once(self) -> None:
        apps = self._fake_applications()
        apps["web-app-keycloak"]["services"]["email"] = {
            "enabled": True,
            "shared": True,
        }

        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-peertube",
            applications=apps,
            service_registry=self._fake_registry(),
            visited=set(),
            rows=rows,
            warnings=[],
        )
        roles_in_rows = [r["role"] for r in rows]
        self.assertEqual(roles_in_rows.count("web-app-keycloak"), 1)
        self.assertEqual(roles_in_rows.count("web-app-mailu"), 1)

    def test_warns_when_shared_service_has_no_provider(self) -> None:
        apps = {
            "web-app-x": {
                "services": {
                    "x": {"cpus": 1},
                    "unknown": {"enabled": True, "shared": True},
                }
            }
        }
        warnings: list = []
        cli.collect_role_resources(
            role_name="web-app-x",
            applications=apps,
            service_registry={},
            visited=set(),
            rows=[],
            warnings=warnings,
        )
        self.assertTrue(any("unknown" in w for w in warnings))

    def test_toggle_only_local_entries_are_skipped(self) -> None:
        apps = {
            "web-app-x": {
                "services": {
                    "x": {"cpus": 1, "mem_limit": "100m"},
                    "feature_flag": {"enabled": True},
                }
            }
        }
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-x",
            applications=apps,
            service_registry={},
            visited=set(),
            rows=rows,
            warnings=[],
        )
        services_in_rows = {r["service"] for r in rows}
        self.assertIn("x", services_in_rows)
        self.assertNotIn("feature_flag", services_in_rows)

    def test_container_sidecar_without_enabled_key_is_counted(self) -> None:
        apps = {
            "web-app-x": {
                "services": {
                    "x": {"cpus": 1, "mem_limit": "100m"},
                    "proxy": {"image": "nginx", "mem_limit": "256m"},
                    "cron": {"mem_limit": "512m"},
                }
            }
        }
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-x",
            applications=apps,
            service_registry={},
            visited=set(),
            rows=rows,
            warnings=[],
        )
        services_in_rows = {r["service"] for r in rows}
        self.assertIn("proxy", services_in_rows)
        self.assertIn("cron", services_in_rows)

    def test_template_gated_shared_service_resolves_to_provider(self) -> None:
        apps = {
            "web-app-hub": {
                "services": {
                    "hub": {"cpus": 1, "mem_limit": "1g"},
                    "matomo": {
                        "enabled": "{{ 'web-app-matomo' in group_names }}",
                        "shared": "{{ 'web-app-matomo' in group_names }}",
                    },
                }
            },
            "web-app-matomo": {
                "services": {
                    "matomo": {"cpus": 2, "mem_limit": "2g", "shared": True},
                }
            },
        }
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-hub",
            applications=apps,
            service_registry={"matomo": {"role": "web-app-matomo"}},
            visited=set(),
            rows=rows,
            warnings=[],
        )
        labels = {(r["role"], r["service"]) for r in rows}
        self.assertIn(("web-app-matomo", "matomo"), labels)

    def _dedup_apps(self) -> dict:
        return {
            "web-app-hub": {
                "services": {
                    "hub": {"cpus": 1, "mem_limit": "1g"},
                    "redis": {"enabled": True, "mem_limit": "100m"},
                    "partner": {"enabled": True, "shared": True},
                }
            },
            "web-app-partner": {
                "services": {
                    "partner": {"cpus": 1, "mem_limit": "1g", "shared": True},
                    "redis": {"enabled": True, "mem_limit": "200m"},
                }
            },
        }

    def test_each_service_loaded_once_by_default(self) -> None:
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-hub",
            applications=self._dedup_apps(),
            service_registry={"partner": {"role": "web-app-partner"}},
            visited=set(),
            rows=rows,
            warnings=[],
        )
        self.assertEqual(len([r for r in rows if r["service"] == "redis"]), 1)

    def test_unshared_lists_each_occurrence(self) -> None:
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-hub",
            applications=self._dedup_apps(),
            service_registry={"partner": {"role": "web-app-partner"}},
            visited=set(),
            rows=rows,
            warnings=[],
            dedup=False,
        )
        self.assertEqual(len([r for r in rows if r["service"] == "redis"]), 2)

    def test_bond_defaults_to_one_when_absent(self) -> None:
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-x",
            applications={"web-app-x": {"services": {"x": {"cpus": 1}}}},
            service_registry={},
            visited=set(),
            rows=rows,
            warnings=[],
        )
        self.assertEqual(rows[0]["bond_float"], 1.0)

    def test_warns_when_role_config_missing(self) -> None:
        warnings: list = []
        cli.collect_role_resources(
            role_name="missing-role",
            applications={},
            service_registry={},
            visited=set(),
            rows=[],
            warnings=warnings,
        )
        self.assertTrue(any("missing-role" in w for w in warnings))

    def test_shared_entry_without_registered_provider_does_not_recurse(self) -> None:
        apps = {
            "web-app-y": {
                "services": {
                    "y": {"cpus": 1, "mem_limit": "100m"},
                    "ghost": {"enabled": True, "shared": True},
                }
            }
        }
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-y",
            applications=apps,
            service_registry={},
            visited=set(),
            rows=rows,
            warnings=[],
        )
        self.assertEqual(
            [(r["role"], r["service"]) for r in rows], [("web-app-y", "y")]
        )


class TestCollectDepth(unittest.TestCase):
    def test_max_depth_stops_recursion(self) -> None:
        apps = {
            "web-app-hub": {
                "services": {
                    "hub": {"cpus": 1, "mem_limit": "1g"},
                    "postgres": {"enabled": True, "shared": True},
                }
            },
            "svc-db-postgres": {
                "services": {"postgres": {"cpus": 2, "mem_limit": "2g", "shared": True}}
            },
        }
        registry = {"postgres": {"role": "svc-db-postgres"}}
        rows: list = []
        cli.collect_role_resources(
            role_name="web-app-hub",
            applications=apps,
            service_registry=registry,
            visited=set(),
            rows=rows,
            warnings=[],
            max_depth=1,
        )
        roles = {r["role"] for r in rows}
        self.assertIn("web-app-hub", roles)
        self.assertNotIn("svc-db-postgres", roles)
        self.assertTrue(all(r["depth"] == 1 for r in rows))


if __name__ == "__main__":
    unittest.main()
