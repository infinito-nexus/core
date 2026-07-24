import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cli.meta.ci.roles.runtime import csvio, github, logparse, render
from cli.meta.ci.roles.runtime.__main__ import main
from utils.cache.files import read_text

SAMPLE_LOG = """\
web-app-keycloak ------------------------------------------------------- 42.50s
sys-svc-mail ----------------------------------------------------------- 30.10s
web-app-keycloak ------------------------------------------------------- 12.40s
sys-svc-mail : Some task -----------------------------------------------  3.00s
total ------------------------------------------------------------------ 93.00s
"""

SEGMENTED_LOG = """\
=== matrix-deploy: round 1/2 inv=/x-0 variants={'web-app-keycloak': 0} apps=['web-app-keycloak'] PASS 1 (sync) ===
TASK [web-app-keycloak : deploy] ***************
ok: [mgr]
web-app-keycloak ------------------------------------------------------- 40.00s
total ------------------------------------------------------------------ 40.00s
=== matrix-deploy: round 1/2 inv=/x-0 variants={'web-app-keycloak': 0} apps=['web-app-keycloak'] PASS 2 (async) ===
web-app-keycloak -------------------------------------------------------- 5.00s
=== matrix-deploy: round 2/2 inv=/x-1 variants={'web-app-keycloak': 1} apps=['web-app-keycloak'] PASS 1 (sync) ===
TASK [web-app-keycloak : deploy] ***************
skipping: [mgr]
web-app-keycloak ------------------------------------------------------- 12.00s
sys-svc-mail ----------------------------------------------------------- 30.00s
"""


def _write(content: str, suffix: str = ".log") -> str:
    fd, name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    Path(name).write_text(content, encoding="utf-8")
    return name


class TestLogParse(unittest.TestCase):
    def _log(self, content: str) -> str:
        name = _write(content)
        self.addCleanup(os.unlink, name)
        return name

    def test_combined_aggregates_keeps_total_and_excludes_task_rows(self):
        records = logparse.parse_log(self._log(SAMPLE_LOG))
        as_dict = {r.role: r.seconds for r in records}
        self.assertAlmostEqual(as_dict["total"], 93.00)
        self.assertTrue(all(" : " not in r.role for r in records))
        self.assertAlmostEqual(as_dict["web-app-keycloak"], 54.90)
        self.assertFalse(records[0].segmented)

    def test_combined_sorted_descending(self):
        records = logparse.parse_log(self._log(SAMPLE_LOG))
        secs = [r.seconds for r in records]
        self.assertEqual(secs, sorted(secs, reverse=True))

    def test_segmented_groups_and_no_bleed(self):
        records = logparse.parse_log(self._log(SEGMENTED_LOG))
        labels = [r.segment_label for r in records]
        self.assertEqual(
            labels,
            [
                "Round 1/2 · PASS 1 (sync)",
                "Round 1/2 · PASS 1 (sync)",
                "Round 1/2 · PASS 2 (async)",
                "Round 2/2 · PASS 1 (sync)",
                "Round 2/2 · PASS 1 (sync)",
            ],
        )
        round1_pass1 = {
            r.role: r.seconds for r in records if r.round == "1" and r.pass_num == "1"
        }
        self.assertEqual(round1_pass1, {"web-app-keycloak": 40.0, "total": 40.0})
        round2 = {r.role: r.seconds for r in records if r.round == "2"}
        self.assertEqual(round2, {"sys-svc-mail": 30.0, "web-app-keycloak": 12.0})

    def test_strips_ansi_and_log_prefix(self):
        log = (
            "\x1b[33mrole-x\x1b[0m --------------------------------------- 5.00s\n"
            "2026-05-22 15:23:23,180 p=985 u=root n=ansible INFO|"
            " role-y ----------------------------------------------- 7.00s\n"
        )
        records = logparse.parse_log(self._log(log))
        self.assertEqual(
            {r.role: r.seconds for r in records}, {"role-x": 5.0, "role-y": 7.0}
        )

    def test_missing_log_raises(self):
        with self.assertRaises(FileNotFoundError):
            logparse.parse_log("/nonexistent/path.log")

    def test_empty_log_returns_empty(self):
        self.assertEqual(logparse.parse_log(self._log("noise\n")), [])

    def test_host_status_executed_skipped_failed_and_delegation(self):
        log = (
            "TASK [role-x : do a thing] ***************\n"
            "ok: [mgr]\n"
            "skipping: [wrk1]\n"
            "changed: [wrk2 -> localhost]\n"
            "TASK [role-y : probe] ***************\n"
            "skipping: [mgr]\n"
            "fatal: [wrk1]: FAILED! => {}\n"
            "role-x ------------------------------------------------------- 5.00s\n"
            "role-y ------------------------------------------------------- 2.00s\n"
        )
        by_role = {r.role: r for r in logparse.parse_log(self._log(log))}
        self.assertEqual(
            by_role["role-x"].host_map,
            {"mgr": "executed", "wrk1": "skipped", "wrk2": "executed"},
        )
        self.assertEqual(
            by_role["role-y"].host_map, {"mgr": "skipped", "wrk1": "failed"}
        )

    def test_ignored_failure_downgrades_to_executed(self):
        log = (
            "TASK [role-x : probe] ***************\n"
            "fatal: [mgr]: FAILED! => {'msg': 'nope'}\n"
            "...ignoring\n"
            "role-x ------------------------------------------------------- 1.00s\n"
        )
        (record,) = logparse.parse_log(self._log(log))
        self.assertEqual(record.host_map, {"mgr": "executed"})

    def test_executed_wins_over_skipped_and_runner_timestamp_stripped(self):
        log = (
            "2026-07-18T19:00:56.9549782Z TASK [role-x : a] ***************\n"
            "2026-07-18T19:00:57.0000000Z skipping: [mgr]\n"
            "2026-07-18T19:00:58.0000000Z ok: [mgr]\n"
            "2026-07-18T19:00:59.0000000Z role-x"
            " ------------------------------------------------------- 1.00s\n"
        )
        (record,) = logparse.parse_log(self._log(log))
        self.assertEqual(record.role, "role-x")
        self.assertEqual(record.host_map, {"mgr": "executed"})

    def test_only_roles_recap_sections_count(self):
        log = (
            "TASKS RECAP ********************\n"
            "some playbook-level task ------------------------------- 9.00s\n"
            "ROLES RECAP ********************\n"
            "role-x ------------------------------------------------- 5.00s\n"
            "ansible.builtin.set_fact ------------------------------- 2.00s\n"
            "total --------------------------------------------------- 7.00s\n"
            "PLAYBOOK RECAP *****************\n"
        )
        as_dict = {r.role: r.seconds for r in logparse.parse_log(self._log(log))}
        self.assertNotIn("some playbook-level task", as_dict)
        self.assertEqual(
            as_dict,
            {"role-x": 5.0, "ansible.builtin.set_fact": 2.0, "total": 7.0},
        )


class TestCsvIo(unittest.TestCase):
    def test_roundtrip(self):
        records = logparse.parse_log(_seg := _write(SEGMENTED_LOG))
        self.addCleanup(os.unlink, _seg)
        csv_name = _write("", ".csv")
        self.addCleanup(os.unlink, csv_name)
        csvio.write_csv(csv_name, records)
        self.assertEqual(csvio.read_csv(csv_name), records)

    def test_header(self):
        self.assertEqual(
            csvio.CSV_HEADER,
            [
                "round",
                "rounds_total",
                "pass",
                "pass_mode",
                "role",
                "seconds",
                "hosts",
            ],
        )


class TestRender(unittest.TestCase):
    def setUp(self):
        self.segmented = logparse.parse_log(_seg := _write(SEGMENTED_LOG))
        self.addCleanup(os.unlink, _seg)
        self.combined = logparse.parse_log(_comb := _write(SAMPLE_LOG))
        self.addCleanup(os.unlink, _comb)

    def test_table_has_label_and_role(self):
        out = render.render(self.segmented, "table")
        self.assertIn("Round 1/2 · PASS 1 (sync)", out)
        self.assertIn("web-app-keycloak", out)

    def test_markdown_segmented_per_variant(self):
        out = render.render(self.segmented, "markdown")
        self.assertIn("## ⏱️ Role runtimes per variant (matrix round)", out)
        self.assertIn("### Round 2/2 · PASS 1 (sync)", out)

    def test_markdown_combined_single_table(self):
        out = render.render(self.combined, "markdown")
        self.assertIn("## ⏱️ Role runtimes", out)
        self.assertNotIn("per variant", out)

    def test_csv_has_header(self):
        out = render.render(self.segmented, "csv")
        self.assertTrue(
            out.startswith("round,rounds_total,pass,pass_mode,role,seconds")
        )

    def test_json_parses(self):
        payload = json.loads(render.render(self.segmented, "json"))
        self.assertEqual(payload[0]["role"], "web-app-keycloak")
        self.assertEqual(payload[0]["pass_mode"], "sync")


_JOB_URL = "https://github.com/o/r/actions/runs/123/job/456"  # nocheck: url
_RUN_URL = "https://github.com/o/r/actions/runs/123"  # nocheck: url


class TestGithubUrl(unittest.TestCase):
    def test_parse_job_url(self):
        self.assertEqual(github.parse_run_ref(_JOB_URL), ("o", "r", "123", "456"))

    def test_parse_run_url_without_job(self):
        self.assertEqual(github.parse_run_ref(_RUN_URL), ("o", "r", "123", None))

    def test_bad_url_raises(self):
        with self.assertRaises(ValueError):
            github.parse_run_ref("https://example.com/not/a/run")


class TestMain(unittest.TestCase):
    def test_missing_log_hard_fails(self):
        self.assertEqual(main(["/nonexistent/path.log"]), 1)

    def test_empty_log_hard_fails(self):
        name = _write("noise\n")
        self.addCleanup(os.unlink, name)
        self.assertEqual(main([name]), 1)

    def test_csv_output_to_file(self):
        log = _write(SEGMENTED_LOG)
        self.addCleanup(os.unlink, log)
        out = _write("", ".csv")
        self.addCleanup(os.unlink, out)
        rc = main([log, "--format", "csv", "--output", out])
        self.assertEqual(rc, 0)
        content = read_text(out)
        self.assertIn("1,2,1,sync,web-app-keycloak,40.00", content)

    def test_markdown_to_stdout(self):
        log = _write(SEGMENTED_LOG)
        self.addCleanup(os.unlink, log)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([log, "--format", "markdown"])
        self.assertEqual(rc, 0)
        self.assertIn("### Round 1/2 · PASS 1 (sync)", buf.getvalue())

    def test_csv_source_autodetected(self):
        log = _write(SEGMENTED_LOG)
        self.addCleanup(os.unlink, log)
        csv_name = _write("", ".csv")
        self.addCleanup(os.unlink, csv_name)
        csvio.write_csv(csv_name, logparse.parse_log(log))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([csv_name, "--format", "table"])
        self.assertEqual(rc, 0)
        self.assertIn("web-app-keycloak", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
