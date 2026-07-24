"""Unit tests for library/database_query.py.

Exercises the building blocks (`_build_cmd`, `_parse_rows`,
`_is_read_only`, `_redact_password_env`, `_escape_value`,
`_substitute_named_args`) directly. The `main()` entrypoint is
integration-tested via the role's playbook — mocking AnsibleModule
stdin/exit_json end-to-end adds churn without catching additional
logic bugs.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from typing import TYPE_CHECKING
from unittest import mock

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

MODULE_PATH = PROJECT_ROOT / "library" / "database_query.py"

sys.path.insert(0, str(PROJECT_ROOT))


def _load_database_query() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_database_query", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_DB_MOD = _load_database_query()

_BASE_CONFIG: dict = {
    "type": "postgres",
    "container": "peertube-database",
    "username": "peertube",
    "name": "peertube",
    "password": "s3cret",
}


class ResolveExecTargetTests(unittest.TestCase):
    def test_compose_no_address_returns_container(self):
        self.assertEqual(
            _DB_MOD._resolve_exec_target(_BASE_CONFIG), "peertube-database"
        )

    def test_compose_address_equals_container_returns_container(self):
        cfg = dict(_BASE_CONFIG, address="peertube-database")
        self.assertEqual(_DB_MOD._resolve_exec_target(cfg), "peertube-database")

    def test_swarm_subshell_address_resolves_to_concrete_id(self):
        cfg = dict(
            _BASE_CONFIG,
            container="postgres",
            address='"$(/usr/bin/resolve-container-id postgres postgres)"',
        )
        fake = mock.Mock(stdout="deadbeefcafe\n")
        with mock.patch.object(_DB_MOD.subprocess, "run", return_value=fake) as run:
            self.assertEqual(_DB_MOD._resolve_exec_target(cfg), "deadbeefcafe")
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/bin/resolve-container-id", "postgres", "postgres"],
        )

    def test_swarm_resolver_empty_falls_back_to_container(self):
        cfg = dict(
            _BASE_CONFIG,
            container="postgres",
            address='"$(/usr/bin/resolve-container-id postgres postgres)"',
        )
        fake = mock.Mock(stdout="\n")
        with mock.patch.object(_DB_MOD.subprocess, "run", return_value=fake):
            self.assertEqual(_DB_MOD._resolve_exec_target(cfg), "postgres")


class BuildCmdPostgresTests(unittest.TestCase):
    def test_postgres_includes_user_db_and_error_stop(self):
        cmd, env = _DB_MOD._build_cmd(_BASE_CONFIG, expect_rows=False)
        self.assertEqual(env, {"PGPASSWORD": "s3cret"})
        self.assertIn("psql", cmd)
        self.assertEqual(cmd[cmd.index("-U") + 1], "peertube")
        self.assertEqual(cmd[cmd.index("-d") + 1], "peertube")
        self.assertIn("ON_ERROR_STOP=1", cmd)
        # Password must NEVER appear in argv (only via env passthrough).
        self.assertNotIn("s3cret", cmd)

    def test_postgres_expect_rows_adds_tuples_only_flag(self):
        cmd, _ = _DB_MOD._build_cmd(_BASE_CONFIG, expect_rows=True)
        self.assertIn("-tA", cmd)

    def test_postgres_no_rows_omits_tuples_only_flag(self):
        cmd, _ = _DB_MOD._build_cmd(_BASE_CONFIG, expect_rows=False)
        self.assertNotIn("-tA", cmd)


class BuildCmdMariadbTests(unittest.TestCase):
    def _mariadb_config(self):
        return dict(_BASE_CONFIG, type="mariadb", container="snipe-database")

    def test_mariadb_prefers_mariadb_binary_by_default(self):
        cmd, env = _DB_MOD._build_cmd(self._mariadb_config(), expect_rows=False)
        self.assertEqual(env, {"MYSQL_PWD": "s3cret"})
        self.assertIn("mariadb", cmd)
        self.assertNotIn("mysql", cmd)
        self.assertEqual(cmd[cmd.index("-u") + 1], "peertube")
        self.assertEqual(cmd[cmd.index("-D") + 1], "peertube")
        self.assertIn("--batch", cmd)
        self.assertNotIn("s3cret", cmd)

    def test_mariadb_falls_back_to_mysql_when_explicitly_requested(self):
        cmd, _ = _DB_MOD._build_cmd(
            self._mariadb_config(), expect_rows=False, binary="mysql"
        )
        self.assertIn("mysql", cmd)
        self.assertNotIn("mariadb", cmd)

    def test_mariadb_expect_rows_adds_skip_column_names(self):
        cmd, _ = _DB_MOD._build_cmd(self._mariadb_config(), expect_rows=True)
        self.assertIn("--skip-column-names", cmd)


class ParseRowsTests(unittest.TestCase):
    def test_postgres_pipe_separated(self):
        rows = _DB_MOD._parse_rows("1|alice\n2|bob\n", db_type="postgres")
        self.assertEqual(rows, [["1", "alice"], ["2", "bob"]])

    def test_mariadb_tab_separated(self):
        rows = _DB_MOD._parse_rows("1\talice\n2\tbob\n", db_type="mariadb")
        self.assertEqual(rows, [["1", "alice"], ["2", "bob"]])

    def test_empty_stdout_returns_empty_list(self):
        self.assertEqual(_DB_MOD._parse_rows("", db_type="postgres"), [])

    def test_blank_line_is_skipped_no_spurious_row(self):
        # `SELECT to_regclass('public.nope')` returns NULL → blank line under -tA.
        self.assertEqual(_DB_MOD._parse_rows("\n", db_type="postgres"), [])


class IsReadOnlyTests(unittest.TestCase):
    def test_select_is_read_only(self):
        self.assertTrue(_DB_MOD._is_read_only("SELECT 1;"))

    def test_select_with_leading_whitespace(self):
        self.assertTrue(_DB_MOD._is_read_only("   \n  SELECT 1;\n"))

    def test_alter_is_not_read_only(self):
        self.assertFalse(_DB_MOD._is_read_only("ALTER TABLE u ADD COLUMN x INT;"))

    def test_insert_is_not_read_only(self):
        self.assertFalse(_DB_MOD._is_read_only("INSERT INTO u (x) VALUES (1);"))

    def test_update_is_not_read_only(self):
        self.assertFalse(_DB_MOD._is_read_only("UPDATE u SET x = 1;"))

    def test_with_cte_is_treated_as_read_only(self):
        # WITH is a CTE prefix — most commonly used in SELECT chains; safe default.
        self.assertTrue(_DB_MOD._is_read_only("WITH x AS (SELECT 1) SELECT * FROM x;"))


class RedactPasswordEnvTests(unittest.TestCase):
    def test_bare_env_name_token_is_kept_intact(self):
        cmd = ["container", "exec", "-i", "-e", "PGPASSWORD", "db", "psql"]
        self.assertEqual(_DB_MOD._redact_password_env(cmd), cmd)

    def test_assignment_form_is_redacted(self):
        cmd = ["container", "exec", "-i", "-e", "PGPASSWORD=s3cret", "db", "psql"]
        out = _DB_MOD._redact_password_env(cmd)
        self.assertIn("PGPASSWORD=<redacted>", out)
        self.assertNotIn("s3cret", " ".join(out))

    def test_mariadb_mysql_pwd_assignment_redacted(self):
        cmd = ["container", "exec", "-e", "MYSQL_PWD=p4ss", "db", "mysql"]
        out = _DB_MOD._redact_password_env(cmd)
        self.assertIn("MYSQL_PWD=<redacted>", out)
        self.assertNotIn("p4ss", " ".join(out))

    def test_unrelated_e_envs_pass_through(self):
        cmd = ["container", "exec", "-e", "FOO=bar", "db", "psql"]
        self.assertEqual(_DB_MOD._redact_password_env(cmd), cmd)


class EscapeValueTests(unittest.TestCase):
    def test_postgres_none_becomes_null_literal(self):
        self.assertEqual(_DB_MOD._escape_value(None, "postgres"), "NULL")

    def test_postgres_bool_becomes_capitalised_literal(self):
        self.assertEqual(_DB_MOD._escape_value(True, "postgres"), "TRUE")
        self.assertEqual(_DB_MOD._escape_value(False, "postgres"), "FALSE")

    def test_postgres_int_and_float_pass_through(self):
        self.assertEqual(_DB_MOD._escape_value(42, "postgres"), "42")
        self.assertEqual(_DB_MOD._escape_value(3.14, "postgres"), "3.14")

    def test_postgres_string_is_single_quoted(self):
        self.assertEqual(_DB_MOD._escape_value("alice", "postgres"), "'alice'")

    def test_postgres_string_doubles_inner_single_quotes(self):
        # canonical postgres-style escape; no E-prefix, standard_conforming_strings on.
        self.assertEqual(_DB_MOD._escape_value("O'Reilly", "postgres"), "'O''Reilly'")

    def test_mariadb_bool_becomes_one_or_zero(self):
        self.assertEqual(_DB_MOD._escape_value(True, "mariadb"), "1")
        self.assertEqual(_DB_MOD._escape_value(False, "mariadb"), "0")

    def test_mariadb_string_backslash_escapes_quote_and_backslash(self):
        self.assertEqual(_DB_MOD._escape_value("a'b", "mariadb"), "'a\\'b'")
        self.assertEqual(_DB_MOD._escape_value("a\\b", "mariadb"), "'a\\\\b'")

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            _DB_MOD._escape_value({"a": 1}, "postgres")
        with self.assertRaises(TypeError):
            _DB_MOD._escape_value([1, 2], "postgres")


class SubstituteNamedArgsTests(unittest.TestCase):
    def test_no_placeholders_returns_sql_unchanged(self):
        sql = "SELECT 1;"
        self.assertEqual(_DB_MOD._substitute_named_args(sql, {}, "postgres"), sql)

    def test_placeholder_substituted_with_escaped_value(self):
        sql = "SELECT * FROM users WHERE name = %(name)s AND age = %(age)s;"
        out = _DB_MOD._substitute_named_args(
            sql, {"name": "alice", "age": 30}, "postgres"
        )
        self.assertEqual(out, "SELECT * FROM users WHERE name = 'alice' AND age = 30;")

    def test_unknown_placeholder_raises_key_error(self):
        sql = "SELECT %(x)s;"
        with self.assertRaisesRegex(KeyError, r"%\(x\)s"):
            _DB_MOD._substitute_named_args(sql, {"y": 1}, "postgres")

    def test_placeholders_without_args_raises_key_error(self):
        sql = "SELECT %(x)s;"
        with self.assertRaisesRegex(KeyError, r"named_args is empty"):
            _DB_MOD._substitute_named_args(sql, {}, "postgres")

    def test_unused_args_are_silently_allowed(self):
        sql = "SELECT %(x)s;"
        out = _DB_MOD._substitute_named_args(
            sql, {"x": 1, "unused": "ignored"}, "postgres"
        )
        self.assertEqual(out, "SELECT 1;")

    def test_quote_inside_value_does_not_break_out_of_string(self):
        sql = "SELECT %(s)s;"
        out = _DB_MOD._substitute_named_args(sql, {"s": "a'b"}, "postgres")
        # Inner ' must be doubled, breaking the trivial SQL-injection vector.
        self.assertEqual(out, "SELECT 'a''b';")

    def test_byte_sequence_not_a_placeholder_passes_through(self):
        # `%(stuff inside string literal` is not a valid identifier-style
        # placeholder — the regex requires a Python identifier in parens.
        sql = "SELECT 'a %( percent thing' AS s;"
        self.assertEqual(_DB_MOD._substitute_named_args(sql, {}, "postgres"), sql)


class EnginesRegistryTests(unittest.TestCase):
    """Guard the dispatch-table shape so new engines stay declarative."""

    REQUIRED_KEYS = (
        "binaries",
        "user_flag",
        "db_flag",
        "shared_flags",
        "rows_flags",
        "row_separator",
        "password_env",
        "string_quote",
        "string_escape_seq",
        "bool_true",
        "bool_false",
    )

    def test_postgres_and_mariadb_are_registered(self):
        self.assertIn("postgres", _DB_MOD._ENGINES)
        self.assertIn("mariadb", _DB_MOD._ENGINES)

    def test_each_engine_has_complete_dialect_definition(self):
        for name, spec in _DB_MOD._ENGINES.items():
            with self.subTest(engine=name):
                for key in self.REQUIRED_KEYS:
                    self.assertIn(key, spec, f"{name!r} missing dialect key {key!r}")

    def test_each_engine_binaries_is_non_empty_tuple(self):
        for name, spec in _DB_MOD._ENGINES.items():
            with self.subTest(engine=name):
                self.assertIsInstance(spec["binaries"], tuple)
                self.assertGreater(len(spec["binaries"]), 0)

    def test_mariadb_prefers_mariadb_over_legacy_mysql(self):
        self.assertEqual(_DB_MOD._ENGINES["mariadb"]["binaries"][0], "mariadb")
        self.assertIn("mysql", _DB_MOD._ENGINES["mariadb"]["binaries"])


class BinaryMissingTests(unittest.TestCase):
    """Guard the narrow trigger for the mariadb→mysql fallback."""

    def _proc(self, rc, stdout="", stderr=""):
        import subprocess as _sp

        return _sp.CompletedProcess(
            args=[], returncode=rc, stdout=stdout, stderr=stderr
        )

    def test_oci_runtime_not_found_message_triggers_fallback(self):
        proc = self._proc(
            127,
            stdout='OCI runtime exec failed: exec failed: unable to start container process: exec: "mariadb": executable file not found in $PATH',
        )
        self.assertTrue(_DB_MOD._binary_missing(proc, "mariadb"))

    def test_rc_127_for_a_different_binary_is_not_matched(self):
        proc = self._proc(
            127,
            stdout='OCI runtime exec failed: exec failed: unable to start container process: exec: "mysql": executable file not found in $PATH',
        )
        self.assertFalse(_DB_MOD._binary_missing(proc, "mariadb"))

    def test_rc_127_without_not_found_string_is_not_matched(self):
        proc = self._proc(127, stderr="ERROR 1064 (42000): syntax error near ...")
        self.assertFalse(_DB_MOD._binary_missing(proc, "mariadb"))

    def test_nonzero_rc_other_than_127_is_not_matched(self):
        proc = self._proc(1, stderr="connection refused")
        self.assertFalse(_DB_MOD._binary_missing(proc, "mariadb"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
