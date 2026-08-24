import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cli.meta.ci.logs.analyze.__main__ import _app_of, _extract, main

_FATAL_LOG = """\
2026-06-26T08:00:00Z | TASK [web-app-keycloak : Update Client settings] ***
2026-06-26T08:00:01Z | fatal: [host]: FAILED! =>
2026-06-26T08:00:01Z |     msg: Failed to create Keycloak object
2026-06-26T08:00:02Z | PLAY RECAP ***
"""

_NO_FATAL_LOG = (
    "2026-06-26T08:00:00Z | ok: [host]\n2026-06-26T08:00:01Z | PLAY RECAP ***\n"
)


class TestExtract(unittest.TestCase):
    @staticmethod
    def _write(text):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as handle:
            handle.write(text)
        return Path(handle.name)

    def test_extracts_task_and_message(self):
        task, message = _extract(self._write(_FATAL_LOG))
        self.assertEqual(task, "web-app-keycloak : Update Client settings")
        self.assertIn("Failed to create Keycloak object", message)

    def test_no_fatal(self):
        task, message = _extract(self._write(_NO_FATAL_LOG))
        self.assertEqual(task, "(no ansible fatal)")
        self.assertEqual(message, "")


class TestAppOf(unittest.TestCase):
    def test_swarm_job_name(self):
        self.assertEqual(
            _app_of(
                Path("/x/123__Orchestrate-test-deploy-swarm-Swarm-web-app-chess.log")
            ),
            "web-app-chess",
        )

    def test_compose_job_name(self):
        self.assertEqual(
            _app_of(Path("/x/9__a-b-Compose-web-app-pihole.log")), "web-app-pihole"
        )

    def test_plain_name(self):
        self.assertEqual(_app_of(Path("/x/9__Lint-Python.log")), "Lint-Python")


class TestMain(unittest.TestCase):
    def test_clusters_same_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            logdir = Path(tmp) / "logs"
            logdir.mkdir()
            (logdir / "1__Swarm-web-app-a.log").write_text(_FATAL_LOG)
            (logdir / "2__Swarm-web-app-b.log").write_text(_FATAL_LOG)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main([tmp])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("2 logs", out)
        self.assertIn("[2]", out)
        self.assertIn("web-app-a", out)

    def test_missing_dir_returns_1(self):
        with redirect_stdout(io.StringIO()):
            rc = main(["/nonexistent/path/xyz"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
