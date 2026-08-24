from __future__ import annotations

import json
import unittest

from cli.meta.roles.applications.ressources import render
from utils.roles.applications.services import resources


class TestRenderText(unittest.TestCase):
    def test_sorts_by_service_then_role_and_uses_labeled_total(self) -> None:
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
        totals = resources.aggregate(rows)
        text = render.render_text("web-app-peertube", rows, totals, warnings=[])

        lines = text.splitlines()
        data_lines = [ln for ln in lines if ln and not ln.startswith(("#", "-"))]
        self.assertTrue(data_lines[0].startswith("service"))
        self.assertTrue(data_lines[1].startswith("peertube"))
        self.assertIn("redis", data_lines[2])
        self.assertIn("web-app-mailu", data_lines[2])
        self.assertIn("redis", data_lines[3])
        self.assertIn("web-app-peertube", data_lines[3])
        self.assertTrue(
            any(
                "TOTAL (mem=SUM, pids=SUM max-provisioned, cpus=MAX)" in ln
                for ln in lines
            )
        )

    def test_appends_warnings_section(self) -> None:
        text = render.render_text(
            role_name="web-app-x",
            rows=[],
            totals=resources.aggregate([]),
            warnings=["shared service 'foo' has no registered provider"],
        )
        self.assertIn("# Warnings", text)
        self.assertIn("! shared service 'foo' has no registered provider", text)


class TestRenderJson(unittest.TestCase):
    def test_emits_services_totals_warnings_and_aggregation_metadata(self) -> None:
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
        totals = resources.aggregate(rows)
        payload = json.loads(
            render.render_json("web-app-peertube", rows, totals, warnings=["w"])
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


class TestRenderSummary(unittest.TestCase):
    def test_summary_text_uses_key_field_and_title(self) -> None:
        rows = [
            {
                "role": "web-app-a",
                "mem_reservation_bytes": 1_000_000_000,
                "mem_limit_bytes": 2_000_000_000,
                "pids_limit_int": 128,
                "cpus_float": 2.0,
            },
            {
                "role": "web-app-b",
                "mem_reservation_bytes": None,
                "mem_limit_bytes": None,
                "pids_limit_int": None,
                "cpus_float": None,
            },
        ]
        text = render.render_summary_text(
            rows, "role", "Footprint per role", warnings=[]
        )
        lines = text.splitlines()
        self.assertIn("# Footprint per role", lines[0])
        self.assertTrue(lines[2].startswith("role"))
        self.assertIn("web-app-a", text)
        self.assertIn("web-app-b", text)

    def test_summary_json_keys_rows_by_field(self) -> None:
        rows = [
            {
                "variant": 0,
                "mem_reservation_bytes": 1_000_000_000,
                "mem_limit_bytes": 2_000_000_000,
                "pids_limit_int": 128,
                "cpus_float": 2.0,
            }
        ]
        payload = json.loads(
            render.render_summary_json(rows, "variant", "per variant", warnings=["w"])
        )
        self.assertEqual(payload["aggregation"], "per variant")
        self.assertEqual(payload["rows"][0]["variant"], 0)
        self.assertEqual(payload["rows"][0]["mem_limit"]["bytes"], 2_000_000_000)
        self.assertEqual(payload["warnings"], ["w"])


if __name__ == "__main__":
    unittest.main()
