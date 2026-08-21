from __future__ import annotations

import unittest
from typing import ClassVar

from cli.administration.deploy.ci import gh, runs
from tests.utils.ci.job_names import deploy_job_name
from tests.utils.ci.run_name import render
from utils.github import run_name


def _job(name: str, conclusion: str | None, status: str = "completed") -> dict:
    return {"name": name, "conclusion": conclusion, "status": status}


class TestParseRoleStatuses(unittest.TestCase):
    def test_maps_compose_and_swarm_jobs_to_modes(self) -> None:
        jobs = [
            _job(deploy_job_name("docker", "web-app-baserow"), "success"),
            _job(deploy_job_name("swarm", "web-app-baserow"), "failure"),
            _job(deploy_job_name("docker", "svc-db-postgres", "0"), "success"),
            _job("🍯 Lure swarms", "success"),
            _job("⛵ Navigate compositions", "success"),
        ]
        statuses = runs.parse_role_statuses(jobs)
        self.assertEqual(
            statuses,
            {
                "web-app-baserow": {"docker": "success", "swarm": "failure"},
                "svc-db-postgres": {"docker": "success"},
            },
        )

    def test_maps_host_jobs_to_modes(self) -> None:
        jobs = [
            _job(deploy_job_name("host", "svc-storage-nfs-server", "0,1"), "failure"),
        ]
        self.assertEqual(
            runs.parse_role_statuses(jobs),
            {"svc-storage-nfs-server": {"host": "failure"}},
        )

    def test_running_job_is_not_completed(self) -> None:
        jobs = [
            _job(deploy_job_name("docker", "web-app-x"), None, status="in_progress")
        ]
        self.assertEqual(
            runs.parse_role_statuses(jobs), {"web-app-x": {"docker": "running"}}
        )

    def test_green_variant_shard_never_masks_a_failed_sibling(self) -> None:
        for shards in (
            [("1", "failure"), ("0", "success")],
            [("0", "success"), ("1", "failure")],
        ):
            with self.subTest(shards=shards):
                jobs = [
                    _job(deploy_job_name("swarm", "web-app-gitlab", variant), state)
                    for variant, state in shards
                ]
                self.assertEqual(
                    runs.parse_role_statuses(jobs),
                    {"web-app-gitlab": {"swarm": "failure"}},
                )

    def test_cancelled_shard_dominates_success_but_not_failure(self) -> None:
        jobs = [
            _job(deploy_job_name("swarm", "web-app-x", "0"), "success"),
            _job(deploy_job_name("swarm", "web-app-x", "1"), "cancelled"),
            _job(deploy_job_name("swarm", "web-app-x", "2"), "failure"),
        ]
        self.assertEqual(
            runs.parse_role_statuses(jobs), {"web-app-x": {"swarm": "failure"}}
        )


class TestAppOfJob(unittest.TestCase):
    def test_extracts_app_from_orchestrated_name(self) -> None:
        name = deploy_job_name("swarm", "web-app-matomo", "0,1")
        self.assertEqual(runs.app_of_job(name), "web-app-matomo")

    def test_none_for_non_deploy_job(self) -> None:
        self.assertIsNone(runs.app_of_job("🍯 Lure swarm"))


class TestParseRoleUrls(unittest.TestCase):
    def test_maps_job_urls_per_mode(self) -> None:
        jobs = [
            {
                "name": deploy_job_name("docker", "web-app-x"),
                "url": "https://gh/c",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "name": deploy_job_name("swarm", "web-app-x"),
                "url": "https://gh/s",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "name": deploy_job_name("swarm", "web-app-y"),
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
    """``total`` is green when every mode that ran is green; an absent mode is N/A."""

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

    def test_missing_mode_is_na_not_failure(self) -> None:
        self.assertEqual(runs.total_state({"docker": "success"}), "success")


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
        "web-app-d": {"docker": "success"},
    }

    def test_total_scope_default(self) -> None:
        self.assertEqual(
            runs.failed_roles(self._STATUSES),
            ["web-app-a", "web-app-c"],
        )

    def test_swarm_scope_skips_roles_without_a_swarm_job(self) -> None:
        self.assertEqual(runs.failed_roles(self._STATUSES, "swarm"), ["web-app-a"])

    def test_docker_scope(self) -> None:
        self.assertEqual(runs.failed_roles(self._STATUSES, "docker"), ["web-app-c"])

    def test_strict_total_excludes_cancelled(self) -> None:
        self.assertEqual(
            runs.failed_roles(self._STATUSES, strict=True),
            ["web-app-a"],
        )

    def test_strict_swarm_keeps_hard_failure(self) -> None:
        self.assertEqual(
            runs.failed_roles(self._STATUSES, "swarm", strict=True), ["web-app-a"]
        )

    def test_strict_docker_excludes_cancelled(self) -> None:
        self.assertEqual(runs.failed_roles(self._STATUSES, "docker", strict=True), [])


class TestRunIdFromUrl(unittest.TestCase):
    def test_extracts_id(self) -> None:
        self.assertEqual(
            gh.run_id_from_url("https://example.com/o/r/actions/runs/28140817070"),
            "28140817070",
        )

    def test_raises_without_id(self) -> None:
        with self.assertRaises(ValueError):
            gh.run_id_from_url("https://example.com/o/r/actions")


class TestSlugFromUrl(unittest.TestCase):
    def test_run_url(self) -> None:
        self.assertEqual(
            gh.slug_from_url(
                "https://github.com/kevinveenbirkenbach/infinito-nexus-core/actions/runs/28141113779/job/83339311104"
            ),
            "kevinveenbirkenbach/infinito-nexus-core",
        )

    def test_ssh_remote(self) -> None:
        self.assertEqual(
            gh.slug_from_url("git@github.com:infinito-nexus/core.git"),
            "infinito-nexus/core",
        )

    def test_https_remote(self) -> None:
        self.assertEqual(
            gh.slug_from_url("https://github.com/owner/repo.git"), "owner/repo"
        )

    def test_raises_on_non_github(self) -> None:
        with self.assertRaises(ValueError):
            gh.slug_from_url("https://example.com/x/y")


class TestInputsFromJobs(unittest.TestCase):
    """The title truncates; a called job's log does not."""

    LOG: ClassVar[str] = "\n".join(
        [
            "2026-08-08T10:22:59.5Z ##[group] Inputs",
            "2026-08-08T10:22:59.5Z   distros: arch",
            "2026-08-08T10:22:59.5Z   whitelist: ",
            "2026-08-08T10:22:59.5Z   priority: "
            + " ".join(f"web-app-{n}" for n in range(69)),
            "2026-08-08T10:22:59.5Z   chunk_gate: true",
            "2026-08-08T10:22:59.5Z ##[endgroup]",
            "2026-08-08T10:22:59.6Z ##[group]Run echo hi",
            "2026-08-08T10:22:59.6Z   priority: not-an-input",
        ]
    )

    def _read(
        self, jobs: list[dict], logs: dict[int, str]
    ) -> tuple[dict[str, str], list[int]]:
        """Read *jobs* against a fake ``gh`` serving *logs* by job id.

        Args:
            jobs: the run's jobs.
            logs: job id -> log body. A missing id stands for a job whose log
                blob does not exist, which ``gh`` reports as a bare HTTP 404.

        Returns:
            the parsed inputs and the job ids the reader asked for, in order.
        """
        asked: list[int] = []

        def fake_gh(
            args: list[str], repo: str | None = None, check: bool = True
        ) -> str:
            self.assertIn("--allow-escape-sequences", args)
            self.assertFalse(check)
            job_id = int(args[-1].split("/")[-2])
            asked.append(job_id)
            return logs.get(job_id, "")

        original = runs._gh
        runs._gh = fake_gh
        try:
            return runs.inputs_from_jobs(jobs, "o/r"), asked
        finally:
            runs._gh = original

    def test_reads_the_full_priority_from_the_first_called_job(self) -> None:
        jobs = [
            {"name": "🎲 Pick distro(s)", "databaseId": 1},
            {"name": "🎛️ Orchestrate CI (manual) / 🏁 Finish pipeline", "databaseId": 2},
        ]

        inputs, asked = self._read(jobs, {2: self.LOG})

        self.assertEqual(asked, [2])
        self.assertEqual(len(inputs["priority"].split()), 69)
        self.assertEqual(inputs["distros"], "arch")
        self.assertEqual(inputs["whitelist"], "")
        self.assertEqual(inputs["chunk_gate"], "true")

    def test_skipped_jobs_are_passed_over(self) -> None:
        """A skipped job uploads no log blob, so reading it is a bare 404."""
        jobs = [
            {
                "name": "🎛️ Orchestrate CI (manual) / test-workspace",
                "databaseId": 1,
                "conclusion": "skipped",
            },
            {
                "name": "🎛️ Orchestrate CI (manual) / 🎯 Selection / ✅ Validation",
                "databaseId": 2,
                "conclusion": "success",
            },
        ]

        inputs, asked = self._read(jobs, {2: self.LOG})

        self.assertEqual(asked, [2])
        self.assertEqual(len(inputs["priority"].split()), 69)

    def test_shallower_jobs_win_over_deeper_ones(self) -> None:
        jobs = [
            {
                "name": "🎛️ Orchestrate CI (manual) / 🎯 Selection / ✅ Validation",
                "databaseId": 2,
                "conclusion": "success",
            },
            {
                "name": "🎛️ Orchestrate CI (manual) / 🏁 Finish pipeline",
                "databaseId": 1,
                "conclusion": "success",
            },
        ]

        _, asked = self._read(jobs, {1: self.LOG, 2: self.LOG})

        self.assertEqual(asked, [1])

    def test_an_expired_log_falls_through_instead_of_aborting(self) -> None:
        jobs = [
            {
                "name": "🎛️ Orchestrate CI (manual) / 🏁 Finish pipeline",
                "databaseId": 1,
                "conclusion": "success",
            },
            {
                "name": "🎛️ Orchestrate CI (manual) / 🎯 Selection / ✅ Validation",
                "databaseId": 2,
                "conclusion": "success",
            },
        ]

        inputs, asked = self._read(jobs, {2: self.LOG})

        self.assertEqual(asked, [1, 2])
        self.assertEqual(len(inputs["priority"].split()), 69)

    def test_a_run_whose_logs_are_all_gone_reads_nothing(self) -> None:
        jobs = [
            {
                "name": "🎛️ Orchestrate CI (manual) / test-workspace",
                "databaseId": 1,
                "conclusion": "skipped",
            },
            {
                "name": "🎛️ Orchestrate CI (manual) / 🏁 Finish pipeline",
                "databaseId": 2,
                "conclusion": "success",
            },
        ]

        inputs, asked = self._read(jobs, {})

        self.assertEqual(asked, [2])
        self.assertEqual(inputs, {})

    def test_a_run_without_a_called_job_reads_nothing(self) -> None:
        self.assertEqual(runs.inputs_from_jobs([{"name": "🎲 Pick"}], "o/r"), {})


class TestConfigFromTitle(unittest.TestCase):
    """A retrigger has to reproduce the source run's configuration.

    The REST API answers ``inputs: null`` for a finished workflow_dispatch, so
    the run title entry-manual-steer.yml builds is the only record of it. Guessing
    wrong is silent: entry-manual-steer.yml defaults to debian alone, so a failure
    that only reproduces on centos comes back green.
    """

    def test_every_config_input_renders_a_segment_in_the_run_name(self) -> None:
        rendered = set(run_name.heads()) | set(run_name.markers())
        self.assertLessEqual(set(runs.CONFIG_INPUTS), rendered)

    def test_the_distros_are_read_back_from_a_manual_run(self) -> None:
        title = render({"distros": "debian arch centos"})
        self.assertEqual(runs.config_from_title(title)["distros"], "debian arch centos")

    def test_a_priority_segment_does_not_bleed_into_them(self) -> None:
        title = render({"distros": "debian", "priority": "web-app-x"})
        self.assertEqual(runs.config_from_title(title)["distros"], "debian")

    def test_the_selection_is_not_part_of_the_configuration(self) -> None:
        title = render({"distros": "debian", "priority": "web-app-x"})
        self.assertNotIn("priority", runs.config_from_title(title))

    def test_a_full_title_round_trips_every_config_input(self) -> None:
        dispatched = {
            "distros": "debian arch",
            "mode": "swarm",
            "lifecycles": "stable",
            "filesystem": "ext4",
            "chunk_gate": "false",
            "workspace": "true",
            "instructions": "false",
        }
        self.assertEqual(runs.config_from_title(render(dispatched)), dispatched)

    def test_a_value_input_on_its_default_records_nothing(self) -> None:
        recovered = runs.config_from_title(render({"distros": "debian"}))
        self.assertEqual(recovered["distros"], "debian")
        self.assertNotIn("mode", recovered)

    def test_a_run_from_another_entry_point_yields_no_override(self) -> None:
        self.assertEqual(runs.config_from_title("CI: Pull Request"), {})

    def test_priority_roles_without_any_job_are_reported(self) -> None:
        statuses = {"web-app-a": {"swarm": "failure"}}
        self.assertEqual(
            runs.untriggered_priority("web-app-a web-app-b web-app-c", statuses),
            ["web-app-b", "web-app-c"],
        )

    def test_a_pinned_priority_entry_keeps_its_axes(self) -> None:
        statuses = {"web-app-a": {"swarm": "failure"}}
        self.assertEqual(
            runs.untriggered_priority(
                "web-app-a#1@compose+tor web-app-b#1@compose+tor "
                "web-app-b#0,2@swarm+clearnet",
                statuses,
            ),
            ["web-app-b#0,2@swarm+clearnet", "web-app-b#1@compose+tor"],
        )

    def test_a_run_without_a_priority_line_reports_nothing(self) -> None:
        self.assertEqual(runs.untriggered_priority("", {}), [])

    def test_a_truncated_priority_entry_aborts_instead_of_passing_through(self) -> None:
        with self.assertRaises(SystemExit):
            runs.untriggered_priority("web-app-a 网络应用·Funkwha...", {})

    def test_the_tor_mode_is_carried_over_from_the_job_log(self) -> None:
        title = render({"mode": "swarm"})
        self.assertEqual(
            runs.config_from_run(title, {"tor": "exclusive"})["tor"], "exclusive"
        )

    def test_a_run_whose_log_records_no_tor_mode_carries_none(self) -> None:
        title = render({"mode": "swarm"})
        self.assertNotIn("tor", runs.config_from_run(title, {}))
        self.assertNotIn("tor", runs.config_from_run(title))


if __name__ == "__main__":
    unittest.main()
