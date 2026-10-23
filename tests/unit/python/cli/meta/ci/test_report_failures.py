from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.meta.ci.report_failures import (
    Failure,
    artifact_name,
    decisive_excerpt,
    failed_roles,
    issue_body,
    list_jobs,
)


class TestReportFailures(unittest.TestCase):
    def test_failed_roles_parses_mode_role_variant(self) -> None:
        jobs = [
            {
                "name": "x / test-deploy-chunk-0 / 🐝🧅 web-app-xwiki#0 ⭐",
                "conclusion": "failure",
            },
            {"name": "y / 🐳🌐 web-app-openproject#0,1,2", "conclusion": "failure"},
            {"name": "🐝🌐 web-svc-logout#1", "conclusion": "timed_out"},
            {"name": "z / 💻 Host / 💻 sys-front-proxy", "conclusion": "failure"},
            {"name": "🐝🌐 web-app-nextcloud#0", "conclusion": "success"},
            {"name": "🧹 Lint", "conclusion": "failure"},
        ]
        self.assertEqual(
            failed_roles(jobs),
            {
                "web-app-xwiki": [Failure("swarm", "0", "tor", "", "", "")],
                "web-app-openproject": [
                    Failure("compose", "0-1-2", "clearnet", "", "", "")
                ],
                "web-svc-logout": [Failure("swarm", "1", "clearnet", "", "", "")],
                "sys-front-proxy": [Failure("host", "", "clearnet", "", "", "")],
            },
        )

    def test_the_same_variant_in_every_network_mode_stays_separate_failures(
        self,
    ) -> None:
        jobs = [
            {"name": "🐳🧅 web-app-xwiki#0 ⭐", "conclusion": "failure"},
            {"name": "🐳🌐 web-app-xwiki#0 ⭐", "conclusion": "failure"},
            {"name": "🐳🌈 web-app-xwiki#0 ⭐", "conclusion": "failure"},
        ]
        self.assertEqual(
            failed_roles(jobs),
            {
                "web-app-xwiki": [
                    Failure("compose", "0", "tor", "", "", ""),
                    Failure("compose", "0", "clearnet", "", "", ""),
                    Failure("compose", "0", "multi", "", "", ""),
                ]
            },
        )

    def test_the_distro_and_filesystem_glyphs_are_read_off_the_title(self) -> None:
        jobs = [{"name": "🐳🌐🌀🦓 web-app-xwiki#0", "conclusion": "failure"}]
        self.assertEqual(
            failed_roles(jobs),
            {
                "web-app-xwiki": [
                    Failure("compose", "0", "clearnet", "debian", "zfs", "")
                ]
            },
        )

    def test_artifact_name(self) -> None:
        self.assertEqual(
            artifact_name(
                "web-app-xwiki", Failure("swarm", "0", "clearnet", "", "", "")
            ),
            "rescue-diagnostics-swarm-web-app-xwiki-0",
        )
        self.assertEqual(
            artifact_name("web-app-x", Failure("compose", "", "clearnet", "", "", "")),
            "rescue-diagnostics-compose-web-app-x",
        )

    def test_the_network_mode_keeps_the_artifact_names_apart(self) -> None:
        names = {
            network: artifact_name(
                "web-app-x", Failure("compose", "0", network, "", "", "")
            )
            for network in ("clearnet", "tor", "multi")
        }
        self.assertEqual(len(set(names.values())), 3)
        self.assertEqual(names["clearnet"], "rescue-diagnostics-compose-web-app-x-0")
        self.assertTrue(names["tor"].endswith("-tor"))
        self.assertTrue(names["multi"].endswith("-multi"))

    def test_the_distro_keeps_two_deploys_of_one_row_apart(self) -> None:
        self.assertNotEqual(
            artifact_name(
                "web-app-x", Failure("compose", "0", "tor", "debian", "zfs", "")
            ),
            artifact_name(
                "web-app-x", Failure("compose", "0", "tor", "fedora", "zfs", "")
            ),
        )

    def test_list_jobs_reads_one_job_per_line_across_pages(self) -> None:
        pages = (
            '{"name": "deploy a", "conclusion": "success"}\n'
            '{"name": "deploy b", "conclusion": "failure"}\n'
        )
        with patch("cli.meta.ci.report_failures._gh", return_value=pages):
            jobs = list_jobs("1", "owner/repo")
        self.assertEqual([job["name"] for job in jobs], ["deploy a", "deploy b"])

    def test_list_jobs_of_an_empty_listing_is_empty(self) -> None:
        with patch("cli.meta.ci.report_failures._gh", return_value=""):
            self.assertEqual(list_jobs("1", "owner/repo"), [])

    def test_issue_body_lists_failures_and_run(self) -> None:
        body = issue_body(
            "web-app-xwiki",
            [
                Failure("swarm", "0", "clearnet", "", "", ""),
                Failure("compose", "", "tor", "", "", ""),
                Failure("swarm", "1", "multi", "", "", ""),
            ],
            run_url="https://gh/run/1",
            excerpt="EXCERPT",
        )
        self.assertIn("web-app-xwiki", body)
        self.assertIn("https://gh/run/1", body)
        self.assertIn("rescue-diagnostics-swarm-web-app-xwiki-0", body)
        self.assertIn("rescue-diagnostics-compose-web-app-xwiki-tor", body)
        self.assertIn("rescue-diagnostics-swarm-web-app-xwiki-1-multi", body)
        self.assertIn("on a `tor` node", body)
        self.assertIn("on a `multi` node", body)
        self.assertNotIn("on a `clearnet` node", body)
        self.assertIn("EXCERPT", body)

    def test_decisive_excerpt_prefers_error_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sub").mkdir()
            (root / "sub" / "error-context.md").write_text("502 backend down\n")
            self.assertIn("502 backend down", decisive_excerpt(root))

    def test_decisive_excerpt_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertIn("No decisive", decisive_excerpt(Path(td)))


if __name__ == "__main__":
    unittest.main()
