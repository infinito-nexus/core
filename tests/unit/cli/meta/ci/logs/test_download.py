import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.ci.logs.download import fetch, github
from cli.meta.ci.logs.download.__main__ import (
    _build_parser,
    _selected_conclusions,
    main,
)

_RUN_URL = "https://github.com/o/r/actions/runs/123"  # nocheck: url


class TestResolveRun(unittest.TestCase):
    def test_url(self):
        self.assertEqual(github.resolve_run(_RUN_URL, None), ("o", "r", "123"))

    def test_url_with_job_suffix(self):
        self.assertEqual(
            github.resolve_run(_RUN_URL + "/job/456", None), ("o", "r", "123")
        )

    def test_bare_id_with_repo_override(self):
        self.assertEqual(
            github.resolve_run("123", "acme/widget"), ("acme", "widget", "123")
        )

    def test_bare_id_resolves_current_repo(self):
        with patch.object(github, "gh", return_value="acme/widget\n"):
            self.assertEqual(github.resolve_run("123", None), ("acme", "widget", "123"))

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            github.resolve_run("not-a-run", None)


class TestSelectedConclusions(unittest.TestCase):
    @staticmethod
    def _ns(**flags):
        base = {"success": False, "failed": False, "cancelled": False, "skipped": False}
        base.update(flags)
        return argparse.Namespace(**base)

    def test_none_selected_returns_none(self):
        self.assertIsNone(_selected_conclusions(self._ns()))

    def test_failed_maps_to_failure(self):
        self.assertEqual(_selected_conclusions(self._ns(failed=True)), {"failure"})

    def test_multiple(self):
        self.assertEqual(
            _selected_conclusions(self._ns(success=True, cancelled=True)),
            {"success", "cancelled"},
        )


class TestWriteManifest(unittest.TestCase):
    def test_writes_jobs_json_and_summary(self):
        jobs = [
            {"id": 1, "name": "A", "conclusion": "failure", "status": "completed"},
            {"id": 2, "name": "B", "conclusion": None, "status": "in_progress"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            fetch.write_manifest(jobs, dest)
            jobs_json = (dest / "jobs.json").read_text()  # nocheck: cache-read
            self.assertEqual(json.loads(jobs_json), jobs)
            summary_text = (dest / "summary.tsv").read_text()  # nocheck: cache-read
            summary = summary_text.splitlines()
            self.assertEqual(summary[0], "id\tconclusion\tstatus\tname")
            self.assertEqual(summary[1], "1\tfailure\tcompleted\tA")
            self.assertEqual(summary[2], "2\t\tin_progress\tB")


class TestParser(unittest.TestCase):
    def test_defaults(self):
        args = _build_parser().parse_args(["123"])
        self.assertEqual(args.run, "123")
        self.assertFalse(args.failed)
        self.assertIsNone(args.destination)

    def test_flags(self):
        args = _build_parser().parse_args(["123", "-f", "-d", "/x", "-j", "4"])
        self.assertTrue(args.failed)
        self.assertEqual(args.destination, "/x")
        self.assertEqual(args.jobs, 4)


class TestMain(unittest.TestCase):
    def test_smoke_no_jobs(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "cli.meta.ci.logs.download.__main__.resolve_run",
                return_value=("o", "r", "1"),
            ),
            patch("cli.meta.ci.logs.download.__main__.list_jobs", return_value=[]),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["1", "--no-artifacts", "-d", tmp])
        self.assertEqual(rc, 0)
        self.assertIn("done", buf.getvalue())

    def test_bad_run_ref_returns_2(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = main(["not-a-run", "--no-logs", "--no-artifacts"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
