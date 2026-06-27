from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from cli.administration.deploy.ci import runs
from cli.administration.deploy.ci.status import __main__ as status

_JOBS = [
    {
        "name": "🐳 Compose web-app-x",
        "status": "completed",
        "conclusion": "success",
        "url": "https://gh/cx",
    },
    {
        "name": "🐝 Swarm web-app-x",
        "status": "completed",
        "conclusion": "failure",
        "url": "https://gh/sx",
    },
    {
        "name": "🐝 Swarm web-app-y",
        "status": "completed",
        "conclusion": "success",
        "url": "https://gh/sy",
    },
]

_URL = "https://github.com/o/r/actions/runs/123"  # nocheck: url


class TestBuildRows(unittest.TestCase):
    def test_run_column_joins_available_job_urls(self) -> None:
        statuses = runs.parse_role_statuses(_JOBS)
        urls = runs.parse_role_urls(_JOBS)
        rows = {r[0]: r for r in status._build_rows(statuses, urls)}
        # web-app-x has both job urls (docker then swarm), web-app-y only swarm
        self.assertEqual(rows["web-app-x"][4], "https://gh/cx https://gh/sx")
        self.assertEqual(rows["web-app-y"][4], "https://gh/sy")

    def test_emoji_cells_and_total(self) -> None:
        statuses = runs.parse_role_statuses(_JOBS)
        rows = {r[0]: r for r in status._build_rows(statuses, {})}
        # x: docker ok, swarm fail -> total fail; y: swarm ok, docker missing -> total fail
        self.assertEqual(rows["web-app-x"][1:4], (runs.PASS, runs.FAIL, runs.FAIL))
        self.assertEqual(rows["web-app-y"][1:4], (runs.MISSING, runs.PASS, runs.FAIL))


class TestRender(unittest.TestCase):
    def test_table_has_run_header_after_total(self) -> None:
        rows = status._build_rows(
            runs.parse_role_statuses(_JOBS), runs.parse_role_urls(_JOBS)
        )
        out = status._render_table(rows)
        header = out.splitlines()[0]
        self.assertRegex(header, r"docker\s+swarm\s+total\s+run")
        self.assertIn("https://gh/sx", out)

    def test_string_format_fields(self) -> None:
        rows = status._build_rows(
            runs.parse_role_statuses(_JOBS), runs.parse_role_urls(_JOBS)
        )
        out = status._render_string(rows)
        line = next(line for line in out.splitlines() if line.startswith("web-app-y"))
        self.assertEqual(
            line, f"web-app-y {runs.MISSING} {runs.PASS} {runs.FAIL} https://gh/sy"
        )


class TestMain(unittest.TestCase):
    def _run(self, argv: list[str]) -> str:
        buf = io.StringIO()
        with (
            mock.patch.object(runs, "fetch_jobs", return_value=_JOBS),
            redirect_stdout(buf),
        ):
            rc = status.main([*argv, "--url", _URL])
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_url_path_renders_all_roles(self) -> None:
        out = self._run([])
        self.assertIn("web-app-x", out)
        self.assertIn("web-app-y", out)

    def test_failed_swarm_filters_to_non_green_swarm(self) -> None:
        out = self._run(["--failed", "swarm"])
        self.assertIn("web-app-x", out)  # swarm failure
        self.assertNotIn("web-app-y", out)  # swarm success -> excluded

    def test_failed_compose_filters_to_non_green_docker(self) -> None:
        out = self._run(["--failed", "compose"])
        self.assertIn("web-app-y", out)  # docker missing
        self.assertNotIn("web-app-x", out)  # docker success -> excluded


if __name__ == "__main__":
    unittest.main()
