"""Unit tests for the `cli.meta.roles.services.called` verifier."""

from __future__ import annotations

import io
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.roles.services.called import (
    _host_log_slice,
    _role_body_executed,
    categories_of,
    required_role_ids,
    verify,
)
from cli.meta.roles.services.called.__main__ import main as cli_main
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_ESC = "\x1b"


def _write_services_yml(role_dir: Path, content: str) -> None:
    services_yml = role_dir / ROLE_FILE_META_SERVICES
    services_yml.parent.mkdir(parents=True, exist_ok=True)
    services_yml.write_text(textwrap.dedent(content))


class TestCategoriesOf(unittest.TestCase):
    def test_web_app(self) -> None:
        self.assertEqual(categories_of("web-app-yourls"), {"web", "web-app"})

    def test_web_svc(self) -> None:
        self.assertEqual(categories_of("web-svc-css"), {"web", "web-svc"})

    def test_svc_db(self) -> None:
        self.assertEqual(categories_of("svc-db-postgres"), {"svc", "svc-db"})

    def test_sys_ctl(self) -> None:
        self.assertEqual(categories_of("sys-ctl-hlth-csp"), {"sys", "sys-ctl"})

    def test_single_segment(self) -> None:
        self.assertEqual(categories_of("desk"), {"desk"})

    def test_empty(self) -> None:
        self.assertEqual(categories_of(""), set())


class TestRoleBodyExecuted(unittest.TestCase):
    def test_wrapper_only_skipping_returns_false(self) -> None:
        log = textwrap.dedent("""
            TASK [foo : include_tasks] *****
            task path: /path/main.yml:2
            skipping: [localhost] =>
        """)
        self.assertFalse(_role_body_executed(log, "foo"))

    def test_multi_wrapper_only_skipping_returns_false(self) -> None:
        """Edge case the count-heuristic would mis-fire on."""
        block = "TASK [foo : include_tasks] *****\nskipping: [localhost] => \n"
        self.assertFalse(_role_body_executed(block * 3, "foo"))

    def test_included_marks_executed(self) -> None:
        log = (
            "TASK [foo : include_tasks] *****\n"
            "task path: /path/main.yml:2\n"
            "included: /path/01_core.yml for localhost\n"
        )
        self.assertTrue(_role_body_executed(log, "foo"))

    def test_ok_marks_executed(self) -> None:
        log = "TASK [foo : Do something] *****\nok: [localhost] => \n"
        self.assertTrue(_role_body_executed(log, "foo"))

    def test_changed_marks_executed(self) -> None:
        log = "TASK [foo : Do something] *****\nchanged: [localhost] => \n"
        self.assertTrue(_role_body_executed(log, "foo"))

    def test_fatal_marks_executed(self) -> None:
        log = "TASK [foo : Do something] *****\nfatal: [localhost]: FAILED! \n"
        self.assertTrue(_role_body_executed(log, "foo"))

    def test_ansi_escape_codes_stripped(self) -> None:
        log = (
            f"{_ESC}[1;30mTASK [foo : include_tasks]{_ESC}[0m ****\n"
            f"{_ESC}[1;30mtask path: …{_ESC}[0m\n"
            f"{_ESC}[0;36mincluded: /path/01_core.yml for localhost{_ESC}[0m\n"
        )
        self.assertTrue(_role_body_executed(log, "foo"))

    def test_mixed_skip_then_run(self) -> None:
        log = (
            "TASK [foo : include_tasks] *****\nskipping: [localhost]\n"
            "TASK [foo : Pull image] *****\nok: [localhost] => \n"
        )
        self.assertTrue(_role_body_executed(log, "foo"))

    def test_other_role_does_not_match(self) -> None:
        log = "TASK [bar : Do something] *****\nok: [localhost]\n"
        self.assertFalse(_role_body_executed(log, "foo"))

    def test_substring_role_id_does_not_match(self) -> None:
        """role_id `foo` must not match `foo-bar` (the colon is the boundary)."""
        log = "TASK [foo-bar : task] *****\nok: [localhost]\n"
        self.assertFalse(_role_body_executed(log, "foo"))

    def test_empty_log_returns_false(self) -> None:
        self.assertFalse(_role_body_executed("", "foo"))


class TestRequiredRoleIds(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_category_match(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-svc-webserver-core",
            """
            ---
            svc-webserver-core:
              required_by:
                categories: [web]
            """,
        )
        result = required_role_ids(
            roles_dir=self.roles_dir, deployed_role_ids=["web-app-yourls"]
        )
        self.assertEqual(result, {"sys-svc-webserver-core"})

    def test_sub_category_match(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-x",
            """
            ---
            x:
              required_by:
                categories: [web-app]
            """,
        )
        result = required_role_ids(
            roles_dir=self.roles_dir, deployed_role_ids=["web-app-yourls"]
        )
        self.assertEqual(result, {"sys-x"})

    def test_no_category_match(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-x",
            """
            ---
            x:
              required_by:
                categories: [svc]
            """,
        )
        result = required_role_ids(
            roles_dir=self.roles_dir, deployed_role_ids=["web-app-yourls"]
        )
        self.assertEqual(result, set())

    def test_explicit_role_match(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-ctl-mtn-cert-deploy",
            """
            ---
            cert-deploy:
              required_by:
                roles: [web-app-mailu]
            """,
        )
        result = required_role_ids(
            roles_dir=self.roles_dir, deployed_role_ids=["web-app-mailu"]
        )
        self.assertEqual(result, {"sys-ctl-mtn-cert-deploy"})

    def test_no_required_by_skipped(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-x",
            """
            ---
            x:
              lifecycle: beta
            """,
        )
        result = required_role_ids(
            roles_dir=self.roles_dir, deployed_role_ids=["web-app-yourls"]
        )
        self.assertEqual(result, set())

    def test_empty_required_by_skipped(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-x",
            """
            ---
            x:
              required_by:
                categories: []
                roles: []
            """,
        )
        result = required_role_ids(
            roles_dir=self.roles_dir, deployed_role_ids=["web-app-yourls"]
        )
        self.assertEqual(result, set())


class TestHostLogSlice(unittest.TestCase):
    def test_reads_full_file_at_zero_offset(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            self.assertEqual(
                _host_log_slice(log_path=path, byte_offset=0), "hello world"
            )
        finally:
            Path(path).unlink()

    def test_reads_from_offset(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            self.assertEqual(_host_log_slice(log_path=path, byte_offset=6), "world")
        finally:
            Path(path).unlink()

    def test_returns_none_when_file_missing(self) -> None:
        self.assertIsNone(
            _host_log_slice(log_path="/nonexistent/path/abc.log", byte_offset=0)
        )


class TestVerifyEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_roles = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmp_roles.name)
        fd, self.log_path = tempfile.mkstemp(suffix=".log")
        import os

        os.close(fd)

    def tearDown(self) -> None:
        self._tmp_roles.cleanup()
        Path(self.log_path).unlink(missing_ok=True)

    def _set_log(self, content: str) -> None:
        Path(self.log_path).write_text(content)

    def test_no_required_roles_returns_ok(self) -> None:
        # No services.yml with required_by present
        self._set_log("")
        ok, missing = verify(
            roles_dir=self.roles_dir,
            log_path=self.log_path,
            deployed_role_ids=["web-app-yourls"],
        )
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_required_role_ran_returns_ok(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-svc-webserver-core",
            """
            ---
            svc-webserver-core:
              required_by:
                categories: [web]
            """,
        )
        self._set_log(
            "TASK [sys-svc-webserver-core : Load OpenResty] ****\nok: [localhost] => \n"
        )
        ok, missing = verify(
            roles_dir=self.roles_dir,
            log_path=self.log_path,
            deployed_role_ids=["web-app-yourls"],
        )
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_required_role_skipped_reports_missing(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-ctl-hlth-csp",
            """
            ---
            csp:
              required_by:
                categories: [web]
            """,
        )
        self._set_log(
            "TASK [sys-ctl-hlth-csp : include_tasks] ****\nskipping: [localhost]\n"
        )
        ok, missing = verify(
            roles_dir=self.roles_dir,
            log_path=self.log_path,
            deployed_role_ids=["web-app-yourls"],
        )
        self.assertFalse(ok)
        self.assertEqual(missing, ["sys-ctl-hlth-csp"])

    def test_missing_log_reports_all_required_missing(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-svc-webserver-core",
            """
            ---
            svc-webserver-core:
              required_by:
                categories: [web]
            """,
        )
        ok, missing = verify(
            roles_dir=self.roles_dir,
            log_path="/nonexistent/log",
            deployed_role_ids=["web-app-yourls"],
        )
        self.assertFalse(ok)
        self.assertEqual(missing, ["sys-svc-webserver-core"])

    def test_byte_offset_limits_scope(self) -> None:
        _write_services_yml(
            self.roles_dir / "sys-svc-webserver-core",
            """
            ---
            svc-webserver-core:
              required_by:
                categories: [web]
            """,
        )
        prefix = "earlier round content\n"
        body = (
            "TASK [sys-svc-webserver-core : Load OpenResty] ****\nok: [localhost] => \n"
        )
        # Scenario: previous-round events at start; current slice starts AFTER them.
        self._set_log(prefix + body)
        # With offset=0 the role's event is in scope → OK.
        ok, missing = verify(
            roles_dir=self.roles_dir,
            log_path=self.log_path,
            deployed_role_ids=["web-app-yourls"],
            log_byte_offset=0,
        )
        self.assertTrue(ok)
        # With offset past the event the slice is empty → role reported missing.
        ok, missing = verify(
            roles_dir=self.roles_dir,
            log_path=self.log_path,
            deployed_role_ids=["web-app-yourls"],
            log_byte_offset=len(prefix) + len(body),
        )
        self.assertFalse(ok)
        self.assertEqual(missing, ["sys-svc-webserver-core"])


class TestCLIMain(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch("sys.argv", ["prog", *argv]),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            try:
                code = cli_main()
            except SystemExit as exc:
                code = int(exc.code if exc.code is not None else 0)
        return code, out.getvalue(), err.getvalue()

    def test_missing_required_args_exits_2(self) -> None:
        code, _, err = self._run([])
        self.assertEqual(code, 2)
        self.assertIn("required", err)

    @patch("cli.meta.roles.services.called.__main__.verify")
    def test_ok_returns_0_and_prints_ok_line(self, mock_verify) -> None:
        mock_verify.return_value = (True, [])
        code, stdout, _ = self._run(
            ["--logfile", "/tmp/dummy.log", "--apps", "web-app-yourls"]
        )
        self.assertEqual(code, 0)
        self.assertIn("OK for web-app-yourls", stdout)

    @patch("cli.meta.roles.services.called.__main__.verify")
    def test_missing_returns_1_and_lists_roles(self, mock_verify) -> None:
        mock_verify.return_value = (False, ["sys-ctl-hlth-csp", "sys-svc-mail"])
        code, _, err = self._run(
            ["--logfile", "/tmp/dummy.log", "--apps", "web-app-yourls"]
        )
        self.assertEqual(code, 1)
        self.assertIn("sys-ctl-hlth-csp", err)
        self.assertIn("sys-svc-mail", err)
        self.assertIn("required_by", err)

    @patch("cli.meta.roles.services.called.__main__.verify")
    def test_apps_csv_split_and_trimmed(self, mock_verify) -> None:
        mock_verify.return_value = (True, [])
        self._run(
            [
                "--logfile",
                "/tmp/dummy.log",
                "--apps",
                " web-app-yourls , web-svc-css ",
            ]
        )
        # verify() was called with the trimmed list
        kwargs = mock_verify.call_args.kwargs
        self.assertEqual(kwargs["deployed_role_ids"], ["web-app-yourls", "web-svc-css"])


if __name__ == "__main__":
    unittest.main()
