from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.meta.ci.report_failures import (
    Failure,
    artifact_name,
    decisive_excerpt,
    failed_roles,
    issue_body,
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
                "web-app-xwiki": [Failure("swarm", "0", True, "", "")],
                "web-app-openproject": [Failure("compose", "0-1-2", False, "", "")],
                "web-svc-logout": [Failure("swarm", "1", False, "", "")],
                "sys-front-proxy": [Failure("host", "", False, "", "")],
            },
        )

    def test_the_same_variant_in_both_onion_states_stays_two_failures(self) -> None:
        jobs = [
            {"name": "🐳🧅 web-app-xwiki#0 ⭐", "conclusion": "failure"},
            {"name": "🐳🌐 web-app-xwiki#0 ⭐", "conclusion": "failure"},
        ]
        self.assertEqual(
            failed_roles(jobs),
            {
                "web-app-xwiki": [
                    Failure("compose", "0", True, "", ""),
                    Failure("compose", "0", False, "", ""),
                ]
            },
        )

    def test_the_distro_and_filesystem_glyphs_are_read_off_the_title(self) -> None:
        jobs = [{"name": "🐳🌐🌀🦓 web-app-xwiki#0", "conclusion": "failure"}]
        self.assertEqual(
            failed_roles(jobs),
            {"web-app-xwiki": [Failure("compose", "0", False, "debian", "zfs")]},
        )

    def test_artifact_name(self) -> None:
        self.assertEqual(
            artifact_name("web-app-xwiki", Failure("swarm", "0", False, "", "")),
            "rescue-diagnostics-swarm-web-app-xwiki-0",
        )
        self.assertEqual(
            artifact_name("web-app-x", Failure("compose", "", False, "", "")),
            "rescue-diagnostics-compose-web-app-x",
        )

    def test_the_onion_state_keeps_the_artifact_names_apart(self) -> None:
        onion = artifact_name("web-app-x", Failure("compose", "0", True, "", ""))
        clear = artifact_name("web-app-x", Failure("compose", "0", False, "", ""))
        self.assertNotEqual(onion, clear)
        self.assertTrue(onion.endswith("-tor"))

    def test_the_distro_keeps_two_deploys_of_one_row_apart(self) -> None:
        self.assertNotEqual(
            artifact_name("web-app-x", Failure("compose", "0", True, "debian", "zfs")),
            artifact_name("web-app-x", Failure("compose", "0", True, "fedora", "zfs")),
        )

    def test_issue_body_lists_failures_and_run(self) -> None:
        body = issue_body(
            "web-app-xwiki",
            [
                Failure("swarm", "0", False, "", ""),
                Failure("compose", "", True, "", ""),
            ],
            run_url="https://gh/run/1",
            excerpt="EXCERPT",
        )
        self.assertIn("web-app-xwiki", body)
        self.assertIn("https://gh/run/1", body)
        self.assertIn("rescue-diagnostics-swarm-web-app-xwiki-0", body)
        self.assertIn("rescue-diagnostics-compose-web-app-xwiki-tor", body)
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
