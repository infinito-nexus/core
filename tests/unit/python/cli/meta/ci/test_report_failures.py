from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.meta.ci.report_failures import (
    _NO_SNAPSHOT,
    Failure,
    _download_excerpt,
    artifact_name,
    decisive_excerpt,
    failed_roles,
    has_snapshot,
    issue_body,
    list_jobs,
)

ROLE = "web-app-nextcloud"
SWARM_0 = Failure("swarm", "0", "clearnet", "debian", "ext4", "amd64")
SWARM_7 = Failure("swarm", "7", "clearnet", "debian", "ext4", "amd64")


def _fake_gh(contents: dict[str, dict[str, str]]):
    """Args:
    contents: artifact name -> {relative path: text} it extracts.

    Returns a ``_gh`` stand-in that extracts like ``gh run download``: it
    refuses to overwrite a file and fails the call, and an unknown artifact
    fails too.
    """

    def gh(args: list[str]) -> str:
        name = args[args.index("-n") + 1]
        target = Path(args[args.index("-D") + 1])
        if name not in contents:
            raise subprocess.CalledProcessError(1, ["gh", *args])
        for rel, text in contents[name].items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(text)
            except FileExistsError as exc:
                raise subprocess.CalledProcessError(1, ["gh", *args]) from exc
        return ""

    return gh


def _artifact(variant: str, error: str) -> dict[str, str]:
    return {
        "host-metrics.log": f"metrics of #{variant}\n",
        f"debian/{ROLE}/error-context.md": error,
    }


class TestDownloadExcerpt(unittest.TestCase):
    def _download(self, contents: dict[str, dict[str, str]], dest: Path) -> str:
        with patch("cli.meta.ci.report_failures._gh", _fake_gh(contents)):
            return _download_excerpt("o/r", "1", ROLE, [SWARM_0, SWARM_7], dest)

    def test_two_artifacts_of_one_role_are_both_extracted(self) -> None:
        names = [artifact_name(ROLE, SWARM_0), artifact_name(ROLE, SWARM_7)]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "rescue"
            excerpt = self._download(
                {
                    names[0]: _artifact("0", "502 from #0\n"),
                    names[1]: _artifact("7", "502 from #7\n"),
                },
                dest,
            )
            expected = [
                f"{name}/{rel}"
                for name, variant in zip(names, ("0", "7"), strict=True)
                for rel in _artifact(variant, "")
            ]
            present = [rel for rel in expected if (dest / rel).is_file()]
            folders = sorted(path.name for path in dest.iterdir())
        self.assertEqual(present, expected)
        self.assertEqual(folders, sorted(names))
        self.assertIn("502 from #0", excerpt)

    def test_host_metrics_alone_is_no_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "rescue"
            excerpt = self._download(
                {artifact_name(ROLE, SWARM_0): {"host-metrics.log": "metrics\n"}},
                dest,
            )
            self.assertFalse(has_snapshot(dest))
        self.assertEqual(excerpt, _NO_SNAPSHOT)

    def test_no_artifact_at_all_is_no_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self._download({}, Path(td) / "rescue"), _NO_SNAPSHOT)

    def test_a_snapshot_without_a_decisive_file_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            excerpt = self._download(
                {
                    artifact_name(ROLE, SWARM_0): {
                        "host-metrics.log": "metrics\n",
                        f"debian/{ROLE}/free.txt": "Swap: 16G 6.8G\n",
                    }
                },
                Path(td) / "rescue",
            )
        self.assertIn("No decisive", excerpt)


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

    def test_a_starred_batch_in_the_caller_path_is_read_past(self) -> None:
        jobs = [
            {
                "name": "x / 0️⃣ Batch ⭐ / 🐝🧅 web-app-xwiki#0",
                "conclusion": "failure",
            },
            {"name": "x / 1️⃣ Batch / 🐳🌐 web-app-xwiki#1", "conclusion": "failure"},
            {"name": "x / 0️⃣ Batch ⭐ / 🔍 Batch 0 ⭐", "conclusion": "failure"},
        ]
        self.assertEqual(
            failed_roles(jobs),
            {
                "web-app-xwiki": [
                    Failure("swarm", "0", "tor", "", "", ""),
                    Failure("compose", "1", "clearnet", "", "", ""),
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
