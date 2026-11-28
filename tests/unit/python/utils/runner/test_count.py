from __future__ import annotations

import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.utils.make_target import run_target
from utils.runner.count import (
    COUNT_KEY,
    FLOOR_KEY,
    RECORD_KEYS,
    Budget,
    CountError,
    Host,
    floor,
    growth,
    load_budget,
    override,
    record_problems,
    report,
    total_ram,
)

GIB = 2**30
RECORD = {
    "applications": ["web-app-dashboard", "web-app-keycloak"],
    "commit": "dde9318aac",
    "date": "2026-11-07",
    "peak_memory": "8g",
    "cpus": 4,
    "disk_growth": "20g",
}
BUDGET = Budget(ram=8 * GIB, cpus=4.0, disk=20 * GIB)
HOST = Host(ram=64 * GIB, cpus=16, free=200 * GIB)
ENV = {COUNT_KEY: "", FLOOR_KEY: "15g"}


def _row(cap_gib: int, used_gib: int | None) -> dict[str, int | None]:
    return {
        "cap_bytes": cap_gib * GIB,
        "used_bytes": None if used_gib is None else used_gib * GIB,
    }


def _calibration(tmp: str, record: dict) -> Path:
    path = Path(tmp) / "runner-calibration.yml"
    path.write_text(
        "".join(f"{key}: {json.dumps(value)}\n" for key, value in record.items())
    )
    return path


class TestTerms(unittest.TestCase):
    def test_the_count_is_the_minimum_of_the_three_terms(self) -> None:
        result = report(HOST, BUDGET, 0, 15 * GIB, None)
        self.assertEqual(result["terms"], {"ram": 8, "cpu": 4, "disk": 9})
        self.assertEqual([result["count"], result["derived"]], [4, 4])

    def test_each_term_can_be_the_binding_one(self) -> None:
        self.assertEqual(
            report(Host(16 * GIB, 64, 999 * GIB), BUDGET, 0, 0, None)["count"], 2
        )
        self.assertEqual(
            report(Host(999 * GIB, 64, 55 * GIB), BUDGET, 0, 15 * GIB, None)["count"], 2
        )

    def test_the_count_is_at_least_one(self) -> None:
        result = report(Host(GIB, 1, GIB), BUDGET, 50 * GIB, 15 * GIB, None)
        self.assertEqual(result["terms"], {"ram": 0, "cpu": 0, "disk": 0})
        self.assertEqual(result["count"], 1)


class TestDiskTerm(unittest.TestCase):
    def test_a_half_full_cache_counts_only_its_remaining_growth(self) -> None:
        self.assertEqual(growth([_row(40, 20)]), 20 * GIB)

    def test_an_over_full_cache_adds_no_negative_growth(self) -> None:
        self.assertEqual(growth([_row(40, 20), _row(20, 30)]), 20 * GIB)

    def test_a_cache_of_unknown_use_counts_with_its_whole_cap(self) -> None:
        self.assertEqual(growth([_row(20, None)]), 20 * GIB)

    def test_the_disk_term_never_subtracts_the_full_cap_sum(self) -> None:
        rows = [_row(40, 20), _row(20, 30), _row(10, 10)]
        result = report(
            Host(999 * GIB, 64, 115 * GIB), BUDGET, growth(rows), 15 * GIB, None
        )
        self.assertEqual(result["growth_bytes"], 20 * GIB)
        self.assertEqual(result["terms"]["disk"], 4)
        full_cap_sum = 70 * GIB
        self.assertNotEqual((115 * GIB - full_cap_sum - 15 * GIB) // BUDGET.disk, 4)


class TestOverride(unittest.TestCase):
    def test_an_empty_override_leaves_the_count_to_the_host(self) -> None:
        self.assertIsNone(override(ENV))

    def test_the_override_wins_over_the_terms(self) -> None:
        pinned = override({**ENV, COUNT_KEY: "7"})
        result = report(HOST, BUDGET, 0, 15 * GIB, pinned)
        self.assertEqual(
            [result["count"], result["derived"], result["override"]], [7, 4, 7]
        )

    def test_the_override_needs_no_calibration(self) -> None:
        result = report(HOST, None, 0, 15 * GIB, 2)
        self.assertEqual([result["count"], result["terms"]], [2, None])

    def test_a_malformed_or_missing_override_is_refused(self) -> None:
        for raw in ("0", "-1", "two", "1.5"):
            with self.subTest(raw=raw), self.assertRaises(CountError):
                override({**ENV, COUNT_KEY: raw})
        with self.assertRaises(CountError):
            override({FLOOR_KEY: "15g"})

    def test_the_floor_comes_from_the_environment(self) -> None:
        self.assertEqual(floor(ENV), 15 * GIB)
        with self.assertRaises(CountError):
            floor({COUNT_KEY: ""})


class TestCalibration(unittest.TestCase):
    def test_a_complete_record_yields_the_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_budget(_calibration(tmp, RECORD)), BUDGET)

    def test_a_budget_without_its_record_is_refused(self) -> None:
        for key in RECORD_KEYS:
            record = {k: v for k, v in RECORD.items() if k != key}
            with self.subTest(missing=key):
                self.assertEqual(record_problems(record), [f"{key} is missing"])
                with (
                    tempfile.TemporaryDirectory() as tmp,
                    self.assertRaises(CountError),
                ):
                    load_budget(_calibration(tmp, record))

    def test_a_malformed_record_is_refused(self) -> None:
        for key, value in (
            ("applications", "web-app-dashboard"),
            ("commit", "HEAD"),
            ("date", "yesterday"),
            ("peak_memory", "lots"),
            ("cpus", "four"),
            ("disk_growth", "0g"),
        ):
            with self.subTest(key=key):
                self.assertEqual(len(record_problems({**RECORD, key: value})), 1)

    def test_no_calibration_and_no_override_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_budget(Path(tmp) / "absent.yml"))
        with self.assertRaises(CountError):
            report(HOST, None, 0, 15 * GIB, None)


class TestHost(unittest.TestCase):
    def test_the_total_ram_comes_from_meminfo(self) -> None:
        meminfo = "MemTotal:       65536000 kB\nMemFree:  1 kB\n"
        self.assertEqual(total_ram(meminfo), 65536000 * 1024)
        with self.assertRaises(CountError):
            total_ram("MemFree: 1 kB\n")


class TestCli(unittest.TestCase):
    def test_the_cli_prints_the_count_and_its_terms(self) -> None:
        cli = importlib.import_module("cli.meta.runner.count.__main__")
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"path": tmp, **_row(10, 0)}, {"path": None, **_row(20, None)}]
            out = io.StringIO()
            with (
                patch.object(cli, "CALIBRATION", _calibration(tmp, RECORD)),
                patch.object(cli, "_cache_rows", return_value=rows),
                patch.dict("os.environ", {**ENV, COUNT_KEY: "3"}),
                contextlib.redirect_stdout(out),
            ):
                code = cli.main()
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual([result["count"], result["growth_bytes"]], [3, 30 * GIB])
        self.assertEqual(set(result["terms"]), {"ram", "cpu", "disk"})

    def test_the_cli_refuses_without_calibration_or_override(self) -> None:
        cli = importlib.import_module("cli.meta.runner.count.__main__")
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with (
                patch.object(cli, "CALIBRATION", Path(tmp) / "absent.yml"),
                patch.object(
                    cli, "_cache_rows", return_value=[{"path": tmp, **_row(1, 0)}]
                ),
                patch.dict("os.environ", ENV),
                contextlib.redirect_stderr(err),
            ):
                code = cli.main()
        self.assertEqual(code, 2)
        self.assertIn("measure a full deploy", err.getvalue())

    def test_the_make_target_runs_the_cli(self) -> None:
        done, calls = run_target("runner-count", (), (), {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(calls, ["python -m cli.meta.runner.count"])


if __name__ == "__main__":
    unittest.main()
