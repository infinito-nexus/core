"""What the generation manifest tells a reader, and what it refuses to guess."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

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
            ("*/payload", ("*/dumps/*.sql.gz", "*/dumps/*.sql")),
        )

    def test_a_generation_without_a_manifest_falls_back_to_the_literals(self) -> None:
        names = manifest.layout_of(tempfile.mkdtemp())
        self.assertEqual(names["files_dir"], layout.FILES_DIR)
        self.assertEqual(names["sql_dir"], layout.SQL_DIR)

    def test_the_fallback_globs_match_the_literal_layout(self) -> None:
        files_glob, dump_globs = manifest.globs_of(
            manifest.layout_of(tempfile.mkdtemp())
        )
        self.assertEqual(files_glob, f"*/{layout.FILES_DIR}")
        self.assertEqual(
            dump_globs,
            (
                f"*/{layout.SQL_DIR}/*.backup.sql.gz",
                f"*/{layout.SQL_DIR}/*.backup.sql",
            ),
        )


class TestLayoutNamesStayInsideTheGeneration(unittest.TestCase):
    VALID: ClassVar[dict[str, str]] = {
        "files_dir": "files",
        "sql_dir": "sql",
        "dump_suffix": ".backup.sql.gz",
        "cluster_suffix": ".cluster.backup.sql.gz",
    }

    def _layout(self, **override: object) -> Path:
        return generation({}, layout_names={**self.VALID, **override})

    def test_single_segment_names_are_returned(self) -> None:
        self.assertEqual(manifest.layout_of(self._layout()), self.VALID)

    def test_the_layout_baudolo_8_writes_is_accepted(self) -> None:
        baudolo_8_layout = {
            "files_dir": "files",
            "sql_dir": "sql",
            "dump_suffix": ".backup.sql.gz",
            "cluster_suffix": ".cluster.backup.sql.gz",
            "dump_compression": "gzip",
        }
        directory = generation({}, layout_names=baudolo_8_layout)
        self.assertEqual(manifest.layout_of(directory), baudolo_8_layout)

    def test_a_field_no_path_is_built_from_is_left_alone(self) -> None:
        names = manifest.layout_of(self._layout(dump_compression=None))
        self.assertIsNone(names["dump_compression"])

    def test_a_missing_name_is_refused_as_unreadable(self) -> None:
        for field in manifest.LAYOUT_NAMES:
            names = {key: value for key, value in self.VALID.items() if key != field}
            with self.subTest(field=field), self.assertRaises(ValueError):
                manifest.layout_of(generation({}, layout_names=names))

    def test_an_absolute_name_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            manifest.layout_of(self._layout(files_dir="/etc"))

    def test_a_parent_reference_is_refused(self) -> None:
        for name in (os.path.pardir, "../outside", "files/.."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manifest.layout_of(self._layout(files_dir=name))

    def test_a_nested_name_is_refused(self) -> None:
        for name in ("a/b", "files/", "./files"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manifest.layout_of(self._layout(sql_dir=name))

    def test_a_suffix_carrying_a_separator_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            manifest.layout_of(self._layout(dump_suffix="/../../x.sql"))

    def test_an_empty_dot_or_non_string_name_is_refused(self) -> None:
        for name in ("", ".", 7, None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manifest.layout_of(self._layout(files_dir=name))

    def test_a_layout_that_is_no_mapping_is_refused(self) -> None:
        directory = Path(tempfile.mkdtemp())
        (directory / MANIFEST_FILE).write_text(
            json.dumps({"schema": MANIFEST_SCHEMA, "layout": ["files"]}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            manifest.layout_of(directory)


class TestDumpSuffixes(unittest.TestCase):
    def test_a_compressed_name_also_finds_the_plain_one(self) -> None:
        self.assertEqual(
            manifest.dump_suffixes(".backup.sql.gz"), (".backup.sql.gz", ".backup.sql")
        )

    def test_negative_control_a_plain_name_finds_only_itself(self) -> None:
        self.assertEqual(manifest.dump_suffixes(".backup.sql"), (".backup.sql",))

    def test_a_generation_stating_the_plain_names_is_walked_with_those(self) -> None:
        directory = generation(
            {},
            layout_names={
                "files_dir": "files",
                "sql_dir": "sql",
                "dump_suffix": ".backup.sql",
                "cluster_suffix": ".cluster.backup.sql",
            },
        )
        self.assertEqual(
            manifest.globs_of(manifest.layout_of(directory))[1],
            ("*/sql/*.backup.sql",),
        )


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
