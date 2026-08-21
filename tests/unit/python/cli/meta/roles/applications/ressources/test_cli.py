from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cli.meta.roles.applications.ressources import __main__ as cli

_APPS = {
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

_VARIANTS = {
    "web-app-x": [
        {"services": {"x": {"mem_limit": "2g", "cpus": 2, "pids_limit": 128}}},
        {"services": {"x": {"mem_limit": "4g", "cpus": 1, "pids_limit": 256}}},
    ]
}


def _run(argv: list[str], *, apps: dict | None = None, variants: dict | None = None):
    apps = _APPS if apps is None else apps
    variants = {} if variants is None else variants
    with (
        patch.object(cli, "load_applications_from_roles_dir", return_value=apps),
        patch.object(cli, "build_service_registry_from_applications", return_value={}),
        patch.object(cli, "get_variants", return_value=variants),
        patch.object(cli.sys, "argv", ["prog", *argv]),
    ):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.main()
    return rc, out.getvalue()


class TestCliDetail(unittest.TestCase):
    """--role X --variant N -> the per-service detail table."""

    def test_text_detail_runs_end_to_end(self) -> None:
        rc, output = _run(
            ["--role", "web-app-x", "--variant", "0"],
            variants={"web-app-x": [_APPS["web-app-x"]]},
        )
        self.assertEqual(rc, 0)
        self.assertIn("web-app-x", output)
        self.assertIn("TOTAL", output)

    def test_json_detail_runs_end_to_end(self) -> None:
        rc, output = _run(
            ["--role", "web-app-x", "--variant", "0", "--format", "json"],
            variants={"web-app-x": [_APPS["web-app-x"]]},
        )
        self.assertEqual(rc, 0)
        payload = json.loads(output)
        self.assertEqual(payload["role"], "web-app-x")
        self.assertEqual(payload["totals"]["mem_limit"]["bytes"], 2_000_000_000)
        self.assertEqual(payload["totals"]["cpus"]["value"], 2.0)


class TestCliAllRoles(unittest.TestCase):
    """No --role -> one summary row per role."""

    def test_text_lists_every_role_without_total(self) -> None:
        rc, output = _run([])
        self.assertEqual(rc, 0)
        self.assertIn("per role", output)
        self.assertIn("web-app-x", output)
        self.assertNotIn("TOTAL", output)

    def test_json_rows_are_keyed_by_role(self) -> None:
        rc, output = _run(["--format", "json"])
        self.assertEqual(rc, 0)
        payload = json.loads(output)
        self.assertEqual(payload["rows"][0]["role"], "web-app-x")
        self.assertEqual(payload["rows"][0]["mem_limit"]["bytes"], 2_000_000_000)


class TestCliRoleVariants(unittest.TestCase):
    """--role X without --variant -> one summary row per variant of X."""

    def test_text_lists_each_variant_without_total(self) -> None:
        rc, output = _run(["--role", "web-app-x"], variants=_VARIANTS)
        self.assertEqual(rc, 0)
        self.assertIn("per variant of web-app-x", output)
        self.assertIn("2 GB", output)
        self.assertIn("4 GB", output)
        self.assertNotIn("TOTAL", output)

    def test_json_rows_are_keyed_by_variant(self) -> None:
        rc, output = _run(
            ["--role", "web-app-x", "--format", "json"], variants=_VARIANTS
        )
        self.assertEqual(rc, 0)
        payload = json.loads(output)
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["rows"][0]["variant"], 0)
        self.assertEqual(payload["rows"][1]["mem_limit"]["bytes"], 4_000_000_000)

    def test_role_without_variants_falls_back_to_base_row(self) -> None:
        rc, output = _run(["--role", "web-app-x"])
        self.assertEqual(rc, 0)
        self.assertIn("per variant of web-app-x", output)
        self.assertIn("base", output)


if __name__ == "__main__":
    unittest.main()
