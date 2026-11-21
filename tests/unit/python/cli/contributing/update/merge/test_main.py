from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cli.contributing.update.merge.__main__ as merge_main
from cli.contributing.update.merge import github

REPO = "infinito-nexus/core"
SHA = "a" * 40
RUN_ID = 111
OWN_RUN_ID = 222
CSV_HEADER = "round,rounds_total,pass,pass_mode,role,seconds,hosts\n"


def pull_request(**overrides):
    pr = {
        "number": 7,
        "state": "open",
        "draft": False,
        "user": {"login": "infinito-nexus-updater[bot]"},
        "head": {
            "sha": SHA,
            "ref": "update/docker-image-versions-20261121-abc1234",
            "repo": {"full_name": REPO},
        },
        "base": {"ref": "main"},
        "labels": [{"name": "update"}, {"name": "minor"}],
    }
    pr.update(overrides)
    return pr


def check(name="🔀 Pull Request / 🏁 Finish pipeline", **overrides):
    run = {
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "details_url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}/job/1",
    }
    run.update(overrides)
    return run


def role_runtimes(*roles):
    rows = "".join(f",,,,{role},1.00,localhost=executed\n" for role in roles)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("role-runtimes-web-app-nextcloud.csv", CSV_HEADER + rows)
    return buffer.getvalue()


class FakeGh:
    """Answers the REST paths the merge gate reads, recording every call.

    Args:
        prs: pull requests associated with ``SHA``.
        checks: check runs on ``SHA``.
        statuses: commit statuses on ``SHA``.
        files: ``filename`` paths the pull request touches.
        artifacts: ``{name: zip bytes}`` of the CI run's artifacts.
    """

    def __init__(self, prs, checks, statuses, files, artifacts):
        self.routes = {
            f"repos/{REPO}/commits/{SHA}/pulls": prs,
            f"repos/{REPO}/commits/{SHA}/check-runs": checks,
            f"repos/{REPO}/commits/{SHA}/status": statuses,
            f"repos/{REPO}/pulls/7/files": [
                {"filename": path, "previous_filename": None} for path in files
            ],
            f"repos/{REPO}/actions/runs/{RUN_ID}/artifacts": [
                {"id": index, "name": name, "expired": False, "size_in_bytes": 512}
                for index, name in enumerate(artifacts)
            ],
        }
        self.blobs = dict(enumerate(artifacts.values()))
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[1] == "--paginate":
            route = args[2].split("?")[0]
            return "\n".join(json.dumps(item) for item in self.routes[route]).encode()
        artifact_id = int(args[1].split("/")[-2])
        return self.blobs[artifact_id]


def green_gh(**overrides):
    fields = {
        "prs": [pull_request()],
        "checks": [check()],
        "statuses": [{"context": "codecov", "state": "success"}],
        "files": ["roles/web-app-nextcloud/meta/services.yml"],
        "artifacts": {
            "role-runtimes-web-app-nextcloud": role_runtimes(
                "web-app-nextcloud", "svc-db-postgres"
            )
        },
    }
    fields.update(overrides)
    return FakeGh(**fields)


def evaluate(gh):
    return merge_main.evaluate(gh, REPO, SHA, RUN_ID, OWN_RUN_ID, "main")


class TestEvaluate(unittest.TestCase):
    def test_all_green_and_every_changed_role_deployed_merges(self):
        pr, refusals = evaluate(green_gh())
        self.assertEqual((pr["number"], refusals), (7, []))

    def test_a_dependabot_pull_request_merges_like_the_updater(self):
        dependabot = pull_request(
            user={"login": "dependabot[bot]"},
            head={
                "sha": SHA,
                "ref": "dependabot/pip/roles/web-app-nextcloud/files/requests-2.32.0",
                "repo": {"full_name": REPO},
            },
        )
        self.assertEqual(evaluate(green_gh(prs=[dependabot]))[1], [])

    def test_a_non_bot_author_is_refused(self):
        human = pull_request(user={"login": "octocat"})
        refusals = evaluate(green_gh(prs=[human]))[1]
        self.assertEqual(refusals, ["author octocat is no update bot"])

    def test_a_missing_update_label_is_refused(self):
        unlabeled = pull_request(labels=[{"name": "minor"}])
        refusals = evaluate(green_gh(prs=[unlabeled]))[1]
        self.assertEqual(refusals, ["label update is missing"])

    def test_a_pending_check_refuses(self):
        pending = check("🌐 Translate catalogs", status="in_progress", conclusion=None)
        refusals = evaluate(green_gh(checks=[check(), pending]))[1]
        self.assertEqual(refusals, ["check 🌐 Translate catalogs is in_progress"])

    def test_a_failed_check_refuses(self):
        failed = check("🔐 CodeQL", conclusion="failure")
        refusals = evaluate(green_gh(checks=[check(), failed]))[1]
        self.assertEqual(refusals, ["check 🔐 CodeQL concluded failure"])

    def test_a_failed_commit_status_refuses(self):
        statuses = [{"context": "codecov", "state": "failure"}]
        refusals = evaluate(green_gh(statuses=statuses))[1]
        self.assertEqual(refusals, ["status codecov is failure"])

    def test_the_deciding_run_own_check_does_not_count(self):
        own = check(
            "🔀 Merge a proven update PR",
            status="in_progress",
            conclusion=None,
            details_url=f"https://github.com/{REPO}/actions/runs/{OWN_RUN_ID}/job/9",
        )
        self.assertEqual(evaluate(green_gh(checks=[check(), own]))[1], [])

    def test_a_changed_role_absent_from_role_runtimes_refuses(self):
        artifacts = {"role-runtimes-web-app-matomo": role_runtimes("web-app-matomo")}
        refusals = evaluate(green_gh(artifacts=artifacts))[1]
        self.assertEqual(
            refusals, ["role web-app-nextcloud changed, but no deploy row ran it"]
        )

    def test_no_role_runtimes_artifact_refuses(self):
        artifacts = {"inventory-web-app-nextcloud": role_runtimes("web-app-nextcloud")}
        refusals = evaluate(green_gh(artifacts=artifacts))[1]
        self.assertEqual(
            refusals, ["no role-runtimes artifact proves web-app-nextcloud"]
        )

    def test_a_pull_request_touching_no_role_needs_no_artifact(self):
        gh = green_gh(files=[".github/workflows/call-lint.yml"], artifacts={})
        self.assertEqual(evaluate(gh)[1], [])
        self.assertFalse(any("artifacts" in " ".join(call) for call in gh.calls))

    def test_no_open_pull_request_for_the_head_refuses(self):
        closed = pull_request(state="closed")
        pr, refusals = evaluate(green_gh(prs=[closed]))
        self.assertIsNone(pr)
        self.assertEqual(refusals, [f"0 open pull requests have head {SHA}, not one"])


class TestMain(unittest.TestCase):
    def run_main(self, gh, sha=SHA):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "github_output"
            argv = [
                "--repo",
                REPO,
                "--sha",
                sha,
                "--run-id",
                str(RUN_ID),
                "--own-run-id",
                str(OWN_RUN_ID),
                "--base",
                "main",
                "--output",
                str(output),
            ]
            stdout = io.StringIO()
            with patch.object(github, "run_gh", gh), redirect_stdout(stdout):
                code = merge_main.main(argv)
            with output.open(encoding="utf-8") as handle:
                return code, handle.read(), stdout.getvalue()

    def test_a_merge_verdict_writes_pr_and_sha(self):
        code, outputs, _ = self.run_main(green_gh())
        self.assertEqual((code, outputs), (0, f"merge=true\npr=7\nsha={SHA}\n"))

    def test_a_refusal_writes_merge_false_and_exits_zero(self):
        gh = green_gh(checks=[check(conclusion="cancelled")])
        code, outputs, printed = self.run_main(gh)
        self.assertEqual((code, outputs), (0, "merge=false\n"))
        self.assertIn("stays open for a manual merge", printed)

    def test_a_short_sha_is_rejected_before_any_call(self):
        gh = green_gh()
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            self.run_main(gh, sha="abc1234")
        self.assertEqual(gh.calls, [])


if __name__ == "__main__":
    unittest.main()
