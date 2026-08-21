#!/usr/bin/env python3
import importlib.util
import os
import tempfile
from pathlib import Path
from unittest import TestCase, main

from . import PROJECT_ROOT


def load_target_module():
    script_path = (
        PROJECT_ROOT
        / "roles"
        / "svc-bkp-volume-2-local"
        / "files"
        / "test"
        / "seed"
        / "marker.py"
    )
    if not script_path.is_file():
        raise FileNotFoundError(f"Target script not found at: {script_path}")
    os.environ.setdefault("BKP_TEST_REPO_ROOT", str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("dr_token", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SCRIPT = load_target_module()


class TestMarkerSql(TestCase):
    def test_postgres_and_mariadb_differ_only_in_the_column_type(self):
        postgres = SCRIPT.marker_sql("postgres", "dr-1-2")
        mariadb = SCRIPT.marker_sql("mariadb", "dr-1-2")
        self.assertIn("token text", postgres)
        self.assertIn("token varchar(64)", mariadb)
        self.assertIn("VALUES ('dr-1-2')", postgres)
        self.assertIn("VALUES ('dr-1-2')", mariadb)

    def test_the_table_is_reset_before_it_is_written(self):
        statement = SCRIPT.marker_sql("postgres", "dr-1-2")
        self.assertLess(statement.index("DROP TABLE"), statement.index("INSERT INTO"))

    def test_a_token_that_could_close_the_quote_is_refused(self):
        for hostile in ("dr'; DROP TABLE users;--", "dr 1", "dr'"):
            with self.assertRaises(SCRIPT.databases.RecoveryError):
                SCRIPT.marker_sql("postgres", hostile)

    def test_the_read_statement_names_the_same_table(self):
        self.assertIn(SCRIPT.MARKER_TABLE, SCRIPT.read_sql())


class TestFileVolumes(TestCase):
    def test_only_volumes_with_a_file_tree_count(self):
        root = Path(tempfile.mkdtemp())
        (root / "openldap_data/files").mkdir(parents=True)
        (root / "zammad_storage/files").mkdir(parents=True)
        (root / "postgres/sql").mkdir(parents=True)
        self.assertEqual(SCRIPT.file_volumes(root), ["openldap_data", "zammad_storage"])


class TestCaptured(TestCase):
    """The half of the proof that runs in both deploy modes."""

    def generation(self, marker_token, dump_body):
        root = Path(tempfile.mkdtemp()) / "gen"
        (root / "openldap_data/files").mkdir(parents=True)
        (root / "postgres/sql").mkdir(parents=True)
        if marker_token is not None:
            (root / "openldap_data/files" / SCRIPT.MARKER_FILE).write_text(marker_token)
        (root / "postgres/sql/zammad.backup.sql").write_text(dump_body)
        return root

    def test_a_generation_carrying_both_passes(self):
        root = self.generation(
            "dr-1-2", "INSERT INTO infinito_dr_marker VALUES ('dr-1-2');\n"
        )
        self.assertEqual(SCRIPT.captured(root, "dr-1-2"), 0)

    def test_a_volume_whose_tree_missed_the_marker_fails(self):
        root = self.generation(
            None, "INSERT INTO infinito_dr_marker VALUES ('dr-1-2');\n"
        )
        with self.assertRaises(SCRIPT.databases.RecoveryError) as raised:
            SCRIPT.captured(root, "dr-1-2")
        self.assertIn("openldap_data", str(raised.exception))

    def test_a_dump_written_without_the_row_fails(self):
        root = self.generation("dr-1-2", "-- empty dump\n")
        with self.assertRaises(SCRIPT.databases.RecoveryError) as raised:
            SCRIPT.captured(root, "dr-1-2")
        self.assertIn("zammad", str(raised.exception))

    def test_a_stale_token_in_the_tree_fails(self):
        root = self.generation(
            "dr-0-0", "INSERT INTO infinito_dr_marker VALUES ('dr-1-2');\n"
        )
        with self.assertRaises(SCRIPT.databases.RecoveryError):
            SCRIPT.captured(root, "dr-1-2")


if __name__ == "__main__":
    main()
