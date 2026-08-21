"""What the generation manifest tells a reader, and what it refuses to guess."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from utils.recovery import layout, manifest
from utils.recovery.layout import MANIFEST_FILE, MANIFEST_SCHEMA


def generation(
    volumes: dict, schema: int = MANIFEST_SCHEMA, layout_names: dict | None = None
) -> Path:
    directory = Path(tempfile.mkdtemp())
    (directory / MANIFEST_FILE).write_text(
        json.dumps(
            {
                "schema": schema,
                "layout": layout_names or {},
                "volumes": volumes,
            }
        ),
        encoding="utf-8",
    )
    return directory


class TestWithoutManifest(unittest.TestCase):
    """A generation written before the manifest existed."""

    def test_read_reports_absence_rather_than_an_empty_verdict(self) -> None:
        self.assertIsNone(manifest.read(tempfile.mkdtemp()))

    def test_the_cli_exits_two_so_a_caller_can_fall_back(self) -> None:
        self.assertEqual(manifest.main([tempfile.mkdtemp()]), 2)


class TestUndumped(unittest.TestCase):
    def test_a_database_volume_without_a_dump_is_reported(self) -> None:
        directory = generation(
            {
                "discourse_database": {
                    "database": True,
                    "dumped": False,
                    "engine": "postgres",
                }
            }
        )
        self.assertEqual(
            manifest.undumped(directory), [("discourse_database", "postgres")]
        )

    def test_a_dumped_database_volume_is_not(self) -> None:
        directory = generation(
            {"pgdata": {"database": True, "dumped": True, "engine": "postgres"}}
        )
        self.assertEqual(manifest.undumped(directory), [])

    def test_a_plain_volume_is_not(self) -> None:
        directory = generation({"assets": {"database": False, "dumped": False}})
        self.assertEqual(manifest.undumped(directory), [])

    def test_a_database_volume_of_unknown_engine_is_still_reported(self) -> None:
        directory = generation({"x": {"database": True, "dumped": False}})
        self.assertEqual(manifest.undumped(directory), [("x", "unknown")])


class TestEngineByVolume(unittest.TestCase):
    def test_it_names_the_engine_the_run_detected(self) -> None:
        directory = generation(
            {
                "pgdata": {"database": True, "dumped": True, "engine": "postgres"},
                "mysqldata": {"database": True, "dumped": True, "engine": "mariadb"},
                "assets": {"database": False, "dumped": False},
            }
        )
        self.assertEqual(
            manifest.engine_by_volume(directory),
            {"pgdata": "postgres", "mysqldata": "mariadb"},
        )


class TestLayoutOf(unittest.TestCase):
    """The generation states its own shape; the literals are only a fallback."""

    def test_a_generation_is_walked_with_the_names_it_recorded(self) -> None:
        directory = generation(
            {},
            layout_names={
                "files_dir": "payload",
                "sql_dir": "dumps",
                "dump_suffix": ".sql.gz",
                "cluster_suffix": ".all.sql.gz",
            },
        )
        self.assertEqual(manifest.layout_of(directory)["files_dir"], "payload")
        self.assertEqual(
            manifest.globs_of(manifest.layout_of(directory)),
            ("*/payload", "*/dumps/*.sql.gz"),
        )

    def test_a_generation_without_a_manifest_falls_back_to_the_literals(self) -> None:
        names = manifest.layout_of(tempfile.mkdtemp())
        self.assertEqual(names["files_dir"], layout.FILES_DIR)
        self.assertEqual(names["sql_dir"], layout.SQL_DIR)

    def test_the_fallback_globs_match_the_literal_layout(self) -> None:
        files_glob, dump_glob = manifest.globs_of(
            manifest.layout_of(tempfile.mkdtemp())
        )
        self.assertEqual(files_glob, f"*/{layout.FILES_DIR}")
        self.assertEqual(dump_glob, f"*/{layout.SQL_DIR}/*{layout.DUMP_SUFFIX}")


class TestSchemaGuard(unittest.TestCase):
    def test_a_newer_schema_is_refused_rather_than_guessed_at(self) -> None:
        directory = generation({}, schema=MANIFEST_SCHEMA + 1)
        with self.assertRaises(ValueError):
            manifest.read(directory)

    def test_a_corrupt_manifest_is_refused(self) -> None:
        directory = Path(tempfile.mkdtemp())
        (directory / MANIFEST_FILE).write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            manifest.read(directory)


if __name__ == "__main__":
    unittest.main()
