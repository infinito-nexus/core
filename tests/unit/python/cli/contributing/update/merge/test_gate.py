from __future__ import annotations

import unittest

from cli.contributing.update.merge import gate

REPO = "infinito-nexus/core"


def pull_request(**overrides):
    pr = {
        "draft": False,
        "user": {"login": "dependabot[bot]"},
        "head": {"ref": "dependabot/npm/left-pad-1.3.0", "repo": {"full_name": REPO}},
        "base": {"ref": "main"},
        "labels": [{"name": "update"}],
    }
    pr.update(overrides)
    return pr


def check(**overrides):
    run = {
        "name": "🧹 Lint",
        "status": "completed",
        "conclusion": "success",
        "details_url": "https://github.com/o/r/actions/runs/1/job/2",
    }
    run.update(overrides)
    return run


class TestPullRequestRefusals(unittest.TestCase):
    def test_an_update_bot_pull_request_passes(self):
        self.assertEqual(gate.pull_request_refusals(pull_request(), REPO, "main"), [])

    def test_a_bot_outside_its_branch_prefix_is_refused(self):
        head = {"ref": "update/sneaky", "repo": {"full_name": REPO}}
        self.assertEqual(
            gate.pull_request_refusals(pull_request(head=head), REPO, "main"),
            ["branch update/sneaky lacks the dependabot/ prefix of dependabot[bot]"],
        )

    def test_a_head_in_another_repository_is_refused(self):
        head = {"ref": "dependabot/npm/x", "repo": {"full_name": "fork/core"}}
        refusals = gate.pull_request_refusals(pull_request(head=head), REPO, "main")
        self.assertEqual(
            refusals, [f"head branch dependabot/npm/x lives outside {REPO}"]
        )

    def test_a_deleted_head_repository_is_refused(self):
        head = {"ref": "dependabot/npm/x", "repo": None}
        refusals = gate.pull_request_refusals(pull_request(head=head), REPO, "main")
        self.assertEqual(len(refusals), 1)

    def test_a_draft_is_refused(self):
        refusals = gate.pull_request_refusals(pull_request(draft=True), REPO, "main")
        self.assertEqual(refusals, ["pull request is a draft"])

    def test_another_base_branch_is_refused(self):
        base = {"ref": "release"}
        refusals = gate.pull_request_refusals(pull_request(base=base), REPO, "main")
        self.assertEqual(refusals, ["base branch is release, not main"])


class TestCheckRefusals(unittest.TestCase):
    def test_skipped_and_neutral_count_as_green(self):
        runs = [check(conclusion="skipped"), check(conclusion="neutral")]
        self.assertEqual(gate.check_refusals(runs, [], own_run_id=9), [])

    def test_no_check_run_at_all_refuses(self):
        self.assertEqual(
            gate.check_refusals([], [], own_run_id=9),
            ["no check run on the head commit"],
        )

    def test_only_the_own_run_left_refuses(self):
        own = check(details_url="https://github.com/o/r/actions/runs/9/job/3")
        self.assertEqual(
            gate.check_refusals([own], [], own_run_id=9),
            ["no check run on the head commit"],
        )

    def test_a_pending_status_refuses(self):
        statuses = [{"context": "ci/external", "state": "pending"}]
        self.assertEqual(
            gate.check_refusals([check()], statuses, own_run_id=9),
            ["status ci/external is pending"],
        )


class TestRoles(unittest.TestCase):
    def test_changed_roles_reads_the_role_directory(self):
        paths = [
            "roles/web-app-nextcloud/meta/services.yml",
            "roles/sys-lint/meta/services.yml",
            "pyproject.toml",
            "docs/roles/web-app-matomo.md",
        ]
        self.assertEqual(gate.changed_roles(paths), {"web-app-nextcloud", "sys-lint"})

    def test_deployed_roles_unions_the_role_column(self):
        first = "role,seconds\nweb-app-nextcloud,3.0\nsvc-db-postgres,1.0\n"
        second = "round,role,seconds\n1,web-app-matomo,2.0\n1,,0.5\n"
        self.assertEqual(
            gate.deployed_roles([first, second]),
            {"web-app-nextcloud", "svc-db-postgres", "web-app-matomo"},
        )

    def test_a_csv_without_a_role_column_proves_nothing(self):
        self.assertEqual(gate.deployed_roles(["name,seconds\nweb-app-x,1\n"]), set())

    def test_no_changed_role_needs_no_proof(self):
        self.assertEqual(gate.role_refusals(set(), []), [])

    def test_every_missing_role_is_named(self):
        csv_text = "role,seconds\nweb-app-nextcloud,1.0\n"
        self.assertEqual(
            gate.role_refusals(
                {"web-app-nextcloud", "web-app-a", "web-app-b"}, [csv_text]
            ),
            [
                "role web-app-a changed, but no deploy row ran it",
                "role web-app-b changed, but no deploy row ran it",
            ],
        )


if __name__ == "__main__":
    unittest.main()
