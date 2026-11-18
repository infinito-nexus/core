"""Unit test: a webhook with a bad signature or a replayed delivery id is
rejected, and a signed one is acted on only through the re-fetched object, so
forged body content raises no trigger and no wrong trust level."""

from __future__ import annotations

import hashlib
import hmac
import unittest

from utils.orchestrator.webhook import (
    Deduplicator,
    Event,
    intake,
    refetch_path,
    verify_signature,
)

SECRET = b"s3cr3t"
REPO = {"full_name": "infinito-nexus/core", "default_branch": "main"}
SHA = "a" * 40


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def _fetcher(objects: dict[str, dict]):
    calls: list[str] = []

    def fetch(path: str) -> dict:
        calls.append(path)
        return objects[path]

    return fetch, calls


class TestSignatureAndReplay(unittest.TestCase):
    def test_a_bad_or_missing_signature_is_rejected(self) -> None:
        body = b'{"action":"completed"}'
        self.assertTrue(verify_signature(SECRET, body, _sign(body)))
        self.assertFalse(verify_signature(SECRET, body + b" ", _sign(body)))
        self.assertFalse(verify_signature(b"other", body, _sign(body)))
        self.assertFalse(verify_signature(SECRET, body, None))
        self.assertFalse(verify_signature(SECRET, body, "sha1=" + "0" * 40))

    def test_a_replayed_delivery_id_is_dropped(self) -> None:
        dedup = Deduplicator()
        self.assertTrue(dedup.seen("72d3162e"))
        self.assertFalse(dedup.seen("72d3162e"))
        self.assertTrue(dedup.seen("72d3162f"))


class TestRefetch(unittest.TestCase):
    def test_a_failed_run_is_read_from_the_fetched_run(self) -> None:
        body = {
            "action": "completed",
            "repository": REPO,
            "workflow_run": {"id": 4711, "conclusion": "failure"},
        }
        path = "/repos/infinito-nexus/core/actions/runs/4711"
        fetch, calls = _fetcher(
            {
                path: {
                    "conclusion": "failure",
                    "head_repository": {"full_name": "infinito-nexus/core"},
                }
            }
        )
        self.assertEqual(
            intake("workflow_run", body, fetch),
            Event("workflow_run_failed", "infinito-nexus/core", False),
        )
        self.assertEqual(calls, [path])

    def test_a_forged_conclusion_raises_no_trigger(self) -> None:
        body = {
            "action": "completed",
            "repository": REPO,
            "workflow_run": {"id": 4711, "conclusion": "failure"},
        }
        fetch, _ = _fetcher(
            {
                "/repos/infinito-nexus/core/actions/runs/4711": {
                    "conclusion": "success",
                    "head_repository": {"full_name": "infinito-nexus/core"},
                }
            }
        )
        self.assertIsNone(intake("workflow_run", body, fetch))

    def test_a_forged_author_association_is_overruled_by_the_fetch(self) -> None:
        body = {
            "action": "opened",
            "repository": REPO,
            "issue": {"number": 12, "author_association": "OWNER"},
        }
        fetch, _ = _fetcher(
            {
                "/repos/infinito-nexus/core/issues/12": {
                    "state": "open",
                    "author_association": "NONE",
                }
            }
        )
        self.assertEqual(
            intake("issues", body, fetch),
            Event("issue_opened", "infinito-nexus/core", True),
        )

    def test_a_fork_pull_request_run_is_an_outsiders(self) -> None:
        body = {"action": "completed", "repository": REPO, "workflow_run": {"id": 9}}
        fetch, _ = _fetcher(
            {
                "/repos/infinito-nexus/core/actions/runs/9": {
                    "conclusion": "failure",
                    "head_repository": {"full_name": "stranger/core"},
                }
            }
        )
        self.assertTrue(intake("workflow_run", body, fetch).outsider)

    def test_a_lockfile_change_on_the_default_branch_is_a_scoped_trigger(
        self,
    ) -> None:
        body = {"ref": "refs/heads/main", "after": SHA, "repository": REPO}
        fetch, _ = _fetcher(
            {
                f"/repos/infinito-nexus/core/commits/{SHA}": {
                    "files": [
                        {"filename": "README.md"},
                        {"filename": "roles/web-app-x/files/package-lock.json"},
                        {"filename": "uv.lock"},
                    ]
                }
            }
        )
        self.assertEqual(
            intake("push", body, fetch),
            Event(
                "dependency_manifest_changed",
                "infinito-nexus/core",
                False,
                ("roles/web-app-x/files/package-lock.json", "uv.lock"),
            ),
        )

    def test_events_the_orchestrator_does_not_act_on(self) -> None:
        cases = (
            ("push", {"ref": "refs/heads/feature/x", "after": SHA, "repository": REPO}),
            (
                "issues",
                {"action": "edited", "repository": REPO, "issue": {"number": 1}},
            ),
            ("workflow_run", {"action": "completed", "repository": REPO}),
            (
                "issues",
                {
                    "action": "opened",
                    "repository": {"full_name": "../../x"},
                    "issue": {"number": 1},
                },
            ),
            ("workflow_run", {"action": "completed", "workflow_run": {"id": "1; x"}}),
            ("star", {"action": "created", "repository": REPO}),
            (
                "issues",
                {
                    "action": "opened",
                    "repository": {"full_name": "infinito-nexus/core\n"},
                    "issue": {"number": 1},
                },
            ),
            (
                "push",
                {"ref": "refs/heads/main", "after": SHA + "\n", "repository": REPO},
            ),
        )
        for kind, body in cases:
            with self.subTest(kind=kind, body=body):
                self.assertIsNone(refetch_path(kind, body))

    def test_a_dot_segment_repository_name_is_never_fetched(self) -> None:
        for name in ("../core", "./..", "infinito-nexus/..", "./core", "/core", "a/"):
            body = {
                "action": "opened",
                "repository": {"full_name": name},
                "issue": {"number": 1},
            }
            with self.subTest(name=name):
                self.assertIsNone(refetch_path("issues", body))

    def test_a_dotted_repository_name_is_still_fetched(self) -> None:
        body = {
            "action": "opened",
            "repository": {"full_name": "infinito-nexus/.github"},
            "issue": {"number": 3},
        }
        self.assertEqual(
            refetch_path("issues", body), "/repos/infinito-nexus/.github/issues/3"
        )


if __name__ == "__main__":
    unittest.main()
