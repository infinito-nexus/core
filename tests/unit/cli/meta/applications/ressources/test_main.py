from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


class TestParsingHelpers(unittest.TestCase):
    def test_parse_mem_bytes_handles_various_units(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        self.assertEqual(cli._parse_mem_bytes("1g"), 1_000_000_000)
        self.assertEqual(cli._parse_mem_bytes("512m"), 512_000_000)
        self.assertEqual(cli._parse_mem_bytes("256M"), 256_000_000)
        self.assertEqual(cli._parse_mem_bytes(1024), 1024)
        self.assertIsNone(cli._parse_mem_bytes(None))
        self.assertIsNone(cli._parse_mem_bytes(""))
        self.assertIsNone(cli._parse_mem_bytes("not-a-size"))

    def test_parse_cpus(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        self.assertEqual(cli._parse_cpus(4), 4.0)
        self.assertEqual(cli._parse_cpus("2.0"), 2.0)
        self.assertEqual(cli._parse_cpus("0.5"), 0.5)
        self.assertIsNone(cli._parse_cpus(None))
        self.assertIsNone(cli._parse_cpus("abc"))

    def test_parse_int(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        self.assertEqual(cli._parse_int(2048), 2048)
        self.assertEqual(cli._parse_int("1024"), 1024)
        self.assertIsNone(cli._parse_int(None))
        self.assertIsNone(cli._parse_int(True))
        self.assertIsNone(cli._parse_int("not-int"))

    def test_is_enabled_primary_defaults_true_when_key_missing(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        self.assertTrue(cli._is_enabled({}, is_primary=True))
        self.assertFalse(cli._is_enabled({}, is_primary=False))

    def test_is_enabled_respects_explicit_flag(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        self.assertTrue(cli._is_enabled({"enabled": True}, is_primary=False))
        self.assertFalse(cli._is_enabled({"enabled": False}, is_primary=True))
        self.assertFalse(cli._is_enabled({"enabled": "false"}, is_primary=True))
        self.assertFalse(cli._is_enabled({"enabled": "0"}, is_primary=True))

    def test_is_enabled_treats_template_strings_as_truthy(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        self.assertTrue(
            cli._is_enabled(
                {"enabled": "{{ RECAPTCHA_ENABLED | bool }}"},
                is_primary=False,
            )
        )

    def test_is_shared(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        self.assertTrue(cli._is_shared({"shared": True}))
        self.assertTrue(cli._is_shared({"shared": "true"}))
        self.assertFalse(cli._is_shared({}))
        self.assertFalse(cli._is_shared({"shared": False}))

    def test_looks_like_container(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        self.assertTrue(cli._looks_like_container({"mem_limit": "256m"}))
        self.assertTrue(cli._looks_like_container({"cpus": 1}))
        self.assertTrue(cli._looks_like_container({"image": "alpine"}))
        self.assertTrue(cli._looks_like_container({"name": "foo", "version": "1"}))
        self.assertFalse(cli._looks_like_container({}))
        self.assertFalse(cli._looks_like_container({"enabled": True}))


class TestAggregate(unittest.TestCase):
    def _row(
        self,
        mem_res: int | None = None,
        mem_lim: int | None = None,
        pids: int | None = None,
        cpus: float | None = None,
    ) -> dict:
        return {
            "role": "r",
            "service": "s",
            "mem_reservation_raw": None,
            "mem_limit_raw": None,
            "pids_limit_raw": None,
            "cpus_raw": None,
            "mem_reservation_bytes": mem_res,
            "mem_limit_bytes": mem_lim,
            "pids_limit_int": pids,
            "cpus_float": cpus,
        }

    def test_sums_mem_and_pids_and_takes_max_cpus(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        rows = [
            self._row(mem_res=1_000, mem_lim=2_000, pids=100, cpus=2.0),
            self._row(mem_res=500, mem_lim=1_000, pids=50, cpus=4.0),
            self._row(mem_res=250, mem_lim=500, pids=25, cpus=1.0),
        ]
        totals = cli.aggregate(rows)
        self.assertEqual(totals["mem_reservation_bytes"], 1_750)
        self.assertEqual(totals["mem_limit_bytes"], 3_500)
        self.assertEqual(totals["pids_limit_int"], 175)
        self.assertEqual(totals["cpus_float"], 4.0)

    def test_returns_none_when_all_values_missing(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        totals = cli.aggregate([self._row(), self._row()])
        self.assertIsNone(totals["mem_reservation_bytes"])
        self.assertIsNone(totals["mem_limit_bytes"])
        self.assertIsNone(totals["pids_limit_int"])
        self.assertIsNone(totals["cpus_float"])

    def test_ignores_none_entries_for_individual_columns(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        rows = [
            self._row(mem_lim=1_000, cpus=2.0),
            self._row(pids=10),
        ]
        totals = cli.aggregate(rows)
        self.assertIsNone(totals["mem_reservation_bytes"])
        self.assertEqual(totals["mem_limit_bytes"], 1_000)
        self.assertEqual(totals["pids_limit_int"], 10)
        self.assertEqual(totals["cpus_float"], 2.0)


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
        from cli.meta.applications.ressources import __main__ as cli

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
        from cli.meta.applications.ressources import __main__ as cli

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
        from cli.meta.applications.ressources import __main__ as cli

        # mailu declares oidc (-> keycloak). keycloak could declare email in
        # theory. Build a cycle keycloak <-> mailu and ensure no infinite loop.
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
        from cli.meta.applications.ressources import __main__ as cli

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
        from cli.meta.applications.ressources import __main__ as cli

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

    def test_warns_when_role_config_missing(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

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

    def test_shared_entry_without_registered_provider_does_not_recurse(
        self,
    ) -> None:
        from cli.meta.applications.ressources import __main__ as cli

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


class TestRenderText(unittest.TestCase):
    def test_sorts_by_service_then_role_and_uses_labeled_total(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        rows = [
            {
                "role": "web-app-peertube",
                "service": "redis",
                "mem_reservation_raw": "256m",
                "mem_limit_raw": "512m",
                "pids_limit_raw": 512,
                "cpus_raw": "0.5",
                "mem_reservation_bytes": 256_000_000,
                "mem_limit_bytes": 512_000_000,
                "pids_limit_int": 512,
                "cpus_float": 0.5,
            },
            {
                "role": "web-app-mailu",
                "service": "redis",
                "mem_reservation_raw": "256m",
                "mem_limit_raw": "512m",
                "pids_limit_raw": 256,
                "cpus_raw": "0.2",
                "mem_reservation_bytes": 256_000_000,
                "mem_limit_bytes": 512_000_000,
                "pids_limit_int": 256,
                "cpus_float": 0.2,
            },
            {
                "role": "web-app-peertube",
                "service": "peertube",
                "mem_reservation_raw": "4g",
                "mem_limit_raw": "8g",
                "pids_limit_raw": 2048,
                "cpus_raw": 4,
                "mem_reservation_bytes": 4_000_000_000,
                "mem_limit_bytes": 8_000_000_000,
                "pids_limit_int": 2048,
                "cpus_float": 4.0,
            },
        ]
        totals = cli.aggregate(rows)
        text = cli.render_text("web-app-peertube", rows, totals, warnings=[])

        lines = text.splitlines()
        data_lines = [ln for ln in lines if ln and not ln.startswith(("#", "-"))]
        # First body line is header, then sorted data rows.
        self.assertTrue(data_lines[0].startswith("service"))
        self.assertTrue(data_lines[1].startswith("peertube"))
        # The two redis rows sort after peertube, mailu before peertube by role.
        self.assertIn("redis", data_lines[2])
        self.assertIn("web-app-mailu", data_lines[2])
        self.assertIn("redis", data_lines[3])
        self.assertIn("web-app-peertube", data_lines[3])
        # Total row uses the labeled form.
        self.assertTrue(
            any(
                "TOTAL (mem=SUM, pids=SUM max-provisioned, cpus=MAX)" in ln
                for ln in lines
            )
        )

    def test_appends_warnings_section(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        text = cli.render_text(
            role_name="web-app-x",
            rows=[],
            totals=cli.aggregate([]),
            warnings=["shared service 'foo' has no registered provider"],
        )
        self.assertIn("# Warnings", text)
        self.assertIn("! shared service 'foo' has no registered provider", text)


class TestRenderJson(unittest.TestCase):
    def test_emits_services_totals_warnings_and_aggregation_metadata(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        rows = [
            {
                "role": "web-app-peertube",
                "service": "peertube",
                "mem_reservation_raw": "4g",
                "mem_limit_raw": "8g",
                "pids_limit_raw": 2048,
                "cpus_raw": 4,
                "mem_reservation_bytes": 4_000_000_000,
                "mem_limit_bytes": 8_000_000_000,
                "pids_limit_int": 2048,
                "cpus_float": 4.0,
            }
        ]
        totals = cli.aggregate(rows)
        payload = json.loads(
            cli.render_json("web-app-peertube", rows, totals, warnings=["w"])
        )
        self.assertEqual(payload["role"], "web-app-peertube")
        self.assertEqual(len(payload["services"]), 1)
        self.assertEqual(payload["totals"]["mem_limit"]["bytes"], 8_000_000_000)
        self.assertEqual(payload["totals"]["cpus"]["value"], 4.0)
        self.assertEqual(payload["totals"]["aggregation"]["cpus"], "max")
        self.assertTrue(
            payload["totals"]["aggregation"]["pids_limit"].startswith("sum")
        )
        self.assertEqual(payload["warnings"], ["w"])


class TestCliMain(unittest.TestCase):
    def test_text_format_runs_end_to_end(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        fake_apps = {
            "web-app-x": {
                "services": {
                    "x": {
                        "cpus": 1,
                        "mem_reservation": "100m",
                        "mem_limit": "200m",
                        "pids_limit": 64,
                    }
                }
            }
        }

        with (
            patch.object(
                cli, "load_applications_from_roles_dir", return_value=fake_apps
            ),
            patch.object(
                cli, "build_service_registry_from_applications", return_value={}
            ),
            patch.object(cli.sys, "argv", ["prog", "--role", "web-app-x"]),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main()

        self.assertEqual(rc, 0)
        output = out.getvalue()
        self.assertIn("web-app-x", output)
        self.assertIn("TOTAL", output)

    def test_json_format_runs_end_to_end(self) -> None:
        from cli.meta.applications.ressources import __main__ as cli

        fake_apps = {
            "web-app-x": {
                "services": {
                    "x": {
                        "cpus": 2,
                        "mem_reservation": "1g",
                        "mem_limit": "2g",
                        "pids_limit": 128,
                    }
                }
            }
        }

        with (
            patch.object(
                cli, "load_applications_from_roles_dir", return_value=fake_apps
            ),
            patch.object(
                cli, "build_service_registry_from_applications", return_value={}
            ),
            patch.object(
                cli.sys,
                "argv",
                ["prog", "--role", "web-app-x", "--format", "json"],
            ),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main()

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["role"], "web-app-x")
        self.assertEqual(payload["totals"]["mem_limit"]["bytes"], 2_000_000_000)
        self.assertEqual(payload["totals"]["cpus"]["value"], 2.0)


if __name__ == "__main__":
    unittest.main()
