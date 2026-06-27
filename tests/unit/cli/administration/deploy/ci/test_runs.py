from __future__ import annotations

import unittest
from typing import ClassVar

from cli.administration.deploy.ci import runs


def _job(name: str, conclusion: str | None, status: str = "completed") -> dict:
    return {"name": name, "conclusion": conclusion, "status": status}


class TestParseRoleStatuses(unittest.TestCase):
    def test_maps_compose_and_swarm_jobs_to_modes(self) -> None:
        jobs = [
            _job("🐳 Compose web-app-baserow", "success"),
            _job("🐝 Swarm web-app-baserow", "failure"),
            _job("test-deploy-compose / 🐳 Compose svc-db-postgres", "success"),
            _job("🍯 Lure swarms", "success"),  # discover job: must be ignored
            _job("⛵ Navigate compositions", "success"),  # discover job: ignored
        ]
        statuses = runs.parse_role_statuses(jobs)
        self.assertEqual(
            statuses,
            {
                "web-app-baserow": {"docker": "success", "swarm": "failure"},
                "svc-db-postgres": {"docker": "success"},
            },
        )

    def test_running_job_is_not_completed(self) -> None:
        jobs = [_job("🐳 Compose web-app-x", None, status="in_progress")]
        self.assertEqual(
            runs.parse_role_statuses(jobs), {"web-app-x": {"docker": "running"}}
        )


class TestParseRoleUrls(unittest.TestCase):
    def test_maps_job_urls_per_mode(self) -> None:
        jobs = [
            {
                "name": "🐳 Compose web-app-x",
                "url": "https://gh/c",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "name": "🐝 Swarm web-app-x",
                "url": "https://gh/s",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "name": "🐝 Swarm web-app-y",
                "url": None,
                "status": "completed",
                "conclusion": "success",
            },
        ]
        self.assertEqual(
            runs.parse_role_urls(jobs),
            {"web-app-x": {"docker": "https://gh/c", "swarm": "https://gh/s"}},
        )


class TestTotalState(unittest.TestCase):
    """``total`` is green only when BOTH modes are green; anything else fails."""

    def test_both_success(self) -> None:
        self.assertEqual(
            runs.total_state({"docker": "success", "swarm": "success"}), "success"
        )

    def test_any_failure_fails(self) -> None:
        self.assertEqual(
            runs.total_state({"docker": "success", "swarm": "failure"}), "failure"
        )

    def test_cancelled_counts_as_failure(self) -> None:
        self.assertEqual(
            runs.total_state({"docker": "success", "swarm": "cancelled"}), "failure"
        )

    def test_running_counts_as_failure(self) -> None:
        self.assertEqual(
            runs.total_state({"docker": "success", "swarm": "running"}), "failure"
        )

    def test_missing_mode_counts_as_failure(self) -> None:
        self.assertEqual(runs.total_state({"docker": "success"}), "failure")


class TestCellSymbols(unittest.TestCase):
    def test_symbol_mapping(self) -> None:
        self.assertEqual(runs.cell("success"), runs.PASS)
        self.assertEqual(runs.cell("failure"), runs.FAIL)
        self.assertEqual(runs.cell("cancelled"), runs.ABORT)
        self.assertEqual(runs.cell("timed_out"), runs.ABORT)
        self.assertEqual(runs.cell("running"), runs.RUNNING)
        self.assertEqual(runs.cell("missing"), runs.MISSING)


class TestFailedRoles(unittest.TestCase):
    _STATUSES: ClassVar[dict[str, dict[str, str]]] = {
        "web-app-b": {"docker": "success", "swarm": "success"},
        "web-app-a": {"docker": "success", "swarm": "failure"},
        "web-app-c": {"docker": "cancelled", "swarm": "success"},
        "web-app-d": {"docker": "success"},  # missing swarm
    }

    def test_total_scope_default(self) -> None:
        self.assertEqual(
            runs.failed_roles(self._STATUSES),
            ["web-app-a", "web-app-c", "web-app-d"],
        )

    def test_swarm_scope(self) -> None:
        # only roles whose swarm mode is not green
        self.assertEqual(
            runs.failed_roles(self._STATUSES, "swarm"), ["web-app-a", "web-app-d"]
        )

    def test_docker_scope(self) -> None:
        # only roles whose docker (compose) mode is not green
        self.assertEqual(runs.failed_roles(self._STATUSES, "docker"), ["web-app-c"])


class TestRunIdFromUrl(unittest.TestCase):
    def test_extracts_id(self) -> None:
        self.assertEqual(
            runs.run_id_from_url("https://example.com/o/r/actions/runs/28140817070"),
            "28140817070",
        )

    def test_raises_without_id(self) -> None:
        with self.assertRaises(ValueError):
            runs.run_id_from_url("https://example.com/o/r/actions")


class TestSlugFromUrl(unittest.TestCase):
    def test_run_url(self) -> None:
        self.assertEqual(
            runs.slug_from_url(
                "https://github.com/kevinveenbirkenbach/infinito-nexus-core/actions/runs/28141113779/job/83339311104"
            ),
            "kevinveenbirkenbach/infinito-nexus-core",
        )

    def test_ssh_remote(self) -> None:
        self.assertEqual(
            runs.slug_from_url("git@github.com:infinito-nexus/core.git"),
            "infinito-nexus/core",
        )

    def test_https_remote(self) -> None:
        self.assertEqual(
            runs.slug_from_url("https://github.com/owner/repo.git"), "owner/repo"
        )

    def test_raises_on_non_github(self) -> None:
        with self.assertRaises(ValueError):
            runs.slug_from_url("https://example.com/x/y")


if __name__ == "__main__":
    unittest.main()
