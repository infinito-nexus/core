"""Unit tests for the `cli.meta.roles.design` work queue."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from cli.meta.roles.design import (
    BASE_PATHS,
    SPEC_FILE,
    DesignCommit,
    GitError,
    RoleFacts,
    build_queue,
    candidate_roles,
    collect_facts,
    not_due,
    reason_of,
    repository_root,
    state_of,
    version_gap,
)
from cli.meta.roles.design.__main__ import main as cli_main
from utils.cache.yaml import dump_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

NEVER_DESIGNED = RoleFacts(
    role="web-app-fresh",
    created=100,
    changed=100,
    designed=None,
    in_review=False,
    base_changed=False,
    designed_version=None,
    current_version="1.0.0",
)
DESIGNED = replace(
    NEVER_DESIGNED,
    role="web-app-designed",
    designed=DesignCommit(sha="a" * 40, timestamp=150),
    designed_version="1.0.0",
)
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _isolate_git(case: unittest.TestCase) -> None:
    """Detach git from the surrounding repository and user for one test.

    Inside a git hook the environment carries ``GIT_DIR`` and ``GIT_INDEX_FILE``
    of the repository being committed, which would redirect every git call of
    the test into that repository. A global ``commit.gpgsign`` would make the
    fixture commits wait for a signing key.

    Args:
        case: Test whose environment is replaced until its cleanup runs.
    """
    scoped = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    env = {key: value for key, value in os.environ.items() if key not in scoped}
    env.update(GIT_IDENTITY, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    patcher = patch.dict(os.environ, env, clear=True)
    patcher.start()
    case.addCleanup(patcher.stop)


class TestVersionGap(unittest.TestCase):
    def test_leading_v_is_ignored(self) -> None:
        self.assertEqual(version_gap("v1.2.3", "1.4.0"), (0, 2, 3))

    def test_short_version_is_padded(self) -> None:
        self.assertEqual(version_gap("2.0", "1.9.9"), (1, 9, 9))

    def test_suffix_behind_the_number_is_ignored(self) -> None:
        self.assertEqual(version_gap("17-3.5", "18-3.5"), (1, 0, 0))

    def test_different_non_numeric_versions_have_the_minimal_gap(self) -> None:
        self.assertEqual(version_gap("latest", "stable"), (0, 0, 1))

    def test_equal_versions_have_no_gap(self) -> None:
        self.assertEqual(version_gap("1.2.3", "1.2.3"), (0, 0, 0))

    def test_equal_non_numeric_versions_have_no_gap(self) -> None:
        self.assertEqual(version_gap("latest", "latest"), (0, 0, 0))

    def test_missing_version_has_the_minimal_gap(self) -> None:
        self.assertEqual(version_gap(None, "1.2.3"), (0, 0, 1))

    def test_two_missing_versions_have_no_gap(self) -> None:
        self.assertEqual(version_gap(None, None), (0, 0, 0))

    def test_change_behind_the_number_has_the_minimal_gap(self) -> None:
        self.assertEqual(version_gap("2.4.0p32", "2.4.0p33"), (0, 0, 1))

    def test_change_in_the_fourth_component_has_the_minimal_gap(self) -> None:
        self.assertEqual(version_gap("1.2.3.4", "1.2.3.9"), (0, 0, 1))


class TestStateOf(unittest.TestCase):
    def test_role_without_design_commit_is_new(self) -> None:
        self.assertEqual(state_of(NEVER_DESIGNED), "new")

    def test_uncommitted_spec_is_in_review(self) -> None:
        self.assertEqual(state_of(replace(NEVER_DESIGNED, in_review=True)), "review")

    def test_review_outranks_a_stale_design(self) -> None:
        facts = replace(DESIGNED, in_review=True, base_changed=True)
        self.assertEqual(state_of(facts), "review")

    def test_base_change_alone_makes_a_design_stale(self) -> None:
        self.assertEqual(state_of(replace(DESIGNED, base_changed=True)), "stale")

    def test_version_gap_alone_makes_a_design_stale(self) -> None:
        self.assertEqual(state_of(replace(DESIGNED, current_version="1.0.1")), "stale")

    def test_unchanged_design_is_current(self) -> None:
        self.assertEqual(state_of(DESIGNED), "current")


class TestReasonOf(unittest.TestCase):
    def test_new_role_was_never_designed(self) -> None:
        self.assertEqual(reason_of(NEVER_DESIGNED), "never designed")

    def test_version_gap_names_both_versions(self) -> None:
        facts = replace(DESIGNED, current_version="2.0.0")
        self.assertEqual(reason_of(facts), "version 1.0.0 -> 2.0.0")

    def test_base_change_is_named(self) -> None:
        facts = replace(DESIGNED, base_changed=True)
        self.assertEqual(reason_of(facts), "design base changed")

    def test_version_gap_and_base_change_are_joined(self) -> None:
        facts = replace(DESIGNED, current_version="2.0.0", base_changed=True)
        self.assertEqual(
            reason_of(facts), "version 1.0.0 -> 2.0.0, design base changed"
        )

    def test_undeclared_version_is_shown_as_none(self) -> None:
        facts = replace(DESIGNED, designed_version=None, current_version="2.0.0")
        self.assertEqual(reason_of(facts), "version none -> 2.0.0")


class TestBuildQueue(unittest.TestCase):
    @staticmethod
    def _roles(facts: list[RoleFacts]) -> list[str]:
        return [entry.role for entry in build_queue(facts)]

    def test_new_roles_come_before_stale_roles(self) -> None:
        stale = replace(
            DESIGNED, role="web-app-a", current_version="9.0.0", changed=999
        )
        new = replace(NEVER_DESIGNED, role="web-app-z", created=1, changed=1)
        self.assertEqual(self._roles([stale, new]), ["web-app-z", "web-app-a"])

    def test_new_roles_are_ordered_newest_first(self) -> None:
        older = replace(NEVER_DESIGNED, role="web-app-a", created=100, changed=900)
        newer = replace(NEVER_DESIGNED, role="web-app-b", created=200, changed=200)
        self.assertEqual(self._roles([older, newer]), ["web-app-b", "web-app-a"])

    def test_stale_roles_are_ordered_by_version_gap_with_base_only_last(self) -> None:
        patch_gap = replace(DESIGNED, role="web-app-patch", current_version="1.0.9")
        major_gap = replace(DESIGNED, role="web-app-major", current_version="2.0.0")
        base_only = replace(
            DESIGNED, role="web-app-base", base_changed=True, changed=999
        )
        minor_gap = replace(DESIGNED, role="web-app-minor", current_version="1.5.0")
        self.assertEqual(
            self._roles([patch_gap, major_gap, base_only, minor_gap]),
            ["web-app-major", "web-app-minor", "web-app-patch", "web-app-base"],
        )

    def test_tie_falls_to_the_most_recently_changed_role(self) -> None:
        quiet = replace(DESIGNED, role="web-app-a", base_changed=True, changed=100)
        busy = replace(DESIGNED, role="web-app-b", base_changed=True, changed=200)
        self.assertEqual(self._roles([quiet, busy]), ["web-app-b", "web-app-a"])

    def test_tie_on_the_change_time_falls_to_the_role_name(self) -> None:
        second = replace(NEVER_DESIGNED, role="web-app-b")
        first = replace(NEVER_DESIGNED, role="web-app-a")
        self.assertEqual(self._roles([second, first]), ["web-app-a", "web-app-b"])

    def test_role_without_commit_sorts_behind_committed_new_roles(self) -> None:
        uncommitted = replace(
            NEVER_DESIGNED, role="web-app-a", created=None, changed=None
        )
        committed = replace(NEVER_DESIGNED, role="web-app-b")
        self.assertEqual(
            self._roles([uncommitted, committed]), ["web-app-b", "web-app-a"]
        )

    def test_review_and_current_roles_are_left_out(self) -> None:
        review = replace(NEVER_DESIGNED, role="web-app-review", in_review=True)
        self.assertEqual(
            self._roles([review, DESIGNED, NEVER_DESIGNED]), ["web-app-fresh"]
        )

    def test_ranks_count_from_one(self) -> None:
        entries = build_queue([replace(DESIGNED, base_changed=True), NEVER_DESIGNED])
        self.assertEqual([entry.rank for entry in entries], [1, 2])


class TestNotDue(unittest.TestCase):
    def test_review_roles_come_before_current_roles_without_a_rank(self) -> None:
        review = replace(NEVER_DESIGNED, role="web-app-review", in_review=True)
        entries = not_due([DESIGNED, NEVER_DESIGNED, review])
        self.assertEqual(
            [(entry.rank, entry.role, entry.state) for entry in entries],
            [
                (None, "web-app-review", "review"),
                (None, "web-app-designed", "current"),
            ],
        )


class TestCandidateRoles(unittest.TestCase):
    CONSUMER: ClassVar[dict[str, bool]] = {"enabled": True}

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.roles_dir = Path(tmp.name)

    def _role(self, name: str, services: dict[str, dict]) -> None:
        dump_yaml(self.roles_dir / name / ROLE_FILE_META_SERVICES, services)

    def test_ui_roles_inside_the_tested_envelope_are_candidates(self) -> None:
        self._role(
            "web-app-demo", {"demo": {"lifecycle": "beta"}, "design": self.CONSUMER}
        )
        self._role("web-svc-demo", {"demo": {"lifecycle": "beta"}})
        self.assertEqual(
            candidate_roles(self.roles_dir), ["web-app-demo", "web-svc-demo"]
        )

    def test_role_without_design_service_is_a_candidate(self) -> None:
        self._role("web-app-demo", {"demo": {"lifecycle": "beta"}})
        self.assertEqual(candidate_roles(self.roles_dir), ["web-app-demo"])

    def test_role_outside_the_tested_envelope_is_skipped(self) -> None:
        self._role(
            "web-app-demo", {"demo": {"lifecycle": "eol"}, "design": self.CONSUMER}
        )
        self.assertEqual(candidate_roles(self.roles_dir), [])

    def test_role_without_lifecycle_is_skipped(self) -> None:
        self._role("web-app-demo", {"demo": {}, "design": self.CONSUMER})
        self.assertEqual(candidate_roles(self.roles_dir), [])

    def test_ui_less_provider_is_skipped(self) -> None:
        self._role(
            "web-svc-cdn", {"cdn": {"lifecycle": "beta"}, "design": self.CONSUMER}
        )
        self.assertEqual(candidate_roles(self.roles_dir), [])

    def test_roles_outside_the_ui_categories_are_skipped(self) -> None:
        for name in ("svc-db-demo", "drv-demo", "web-opt-rdr-demo", "update"):
            self._role(name, {"demo": {"lifecycle": "beta"}, "design": self.CONSUMER})
        self._role("sys-front-inj-design", {"design": {"lifecycle": "beta"}})
        self.assertEqual(candidate_roles(self.roles_dir), [])

    def test_directory_without_services_file_is_skipped(self) -> None:
        (self.roles_dir / "web-app-demo").mkdir()
        self.assertEqual(candidate_roles(self.roles_dir), [])


class TestCollectFacts(unittest.TestCase):
    ROLE: ClassVar[str] = "web-app-demo"
    SPEC: ClassVar[str] = f"roles/{ROLE}/{SPEC_FILE}"
    README: ClassVar[str] = f"roles/{ROLE}/README.md"
    BASE: ClassVar[str] = BASE_PATHS[-1]
    EPOCH: ClassVar[int] = 1_700_000_000

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        _isolate_git(self)
        self._git("init", "--quiet", "-b", "main")
        self._declare(self.ROLE, "1.0.0")
        self._write(self.BASE, "BASE = 1\n")
        self._commit("add the role", self.EPOCH)

    def _git(self, *args: str, **env: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def _write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _declare(self, role: str, version: str) -> None:
        dump_yaml(
            self.root / "roles" / role / ROLE_FILE_META_SERVICES,
            {
                role.removeprefix("web-app-"): {
                    "version": version,
                    "lifecycle": "beta",
                },
                "design": {"enabled": True},
            },
        )

    @staticmethod
    def _dated(timestamp: int) -> dict[str, str]:
        date = f"{timestamp} +0000"
        return {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}

    def _commit(self, message: str, timestamp: int) -> str:
        self._git("add", "--all")
        self._git("commit", "--quiet", "--message", message, **self._dated(timestamp))
        return self._git("rev-parse", "HEAD")

    def _design(self, timestamp: int) -> str:
        self._write(self.SPEC, "// design spec\n")
        return self._commit("design pass", timestamp)

    def _move_base(self, timestamp: int) -> None:
        self._write(self.BASE, "BASE = 2\n")
        self._commit("move the design base", timestamp)

    def _facts_of(self, role: str) -> RoleFacts:
        return next(facts for facts in collect_facts(self.root) if facts.role == role)

    def _facts(self) -> RoleFacts:
        return self._facts_of(self.ROLE)

    def _index(self) -> bytes:
        with (self.root / ".git" / "index").open("rb") as handle:
            return handle.read()

    def test_state_follows_the_role_history(self) -> None:
        states = [state_of(self._facts())]
        self._design(self.EPOCH + 60)
        states.append(state_of(self._facts()))
        self._move_base(self.EPOCH + 120)
        self._declare(self.ROLE, "2.0.0")
        states.append(state_of(self._facts()))
        self.assertEqual(states, ["new", "current", "stale"])

    def test_untracked_spec_is_in_review(self) -> None:
        self._write(self.SPEC, "// design spec\n")
        self.assertTrue(self._facts().in_review)

    def test_untracked_spec_is_in_review_when_git_hides_untracked_files(self) -> None:
        self._git("config", "status.showUntrackedFiles", "no")
        self._write(self.SPEC, "// design spec\n")
        self.assertTrue(self._facts().in_review)

    def test_modified_spec_is_in_review(self) -> None:
        self._design(self.EPOCH + 60)
        self._write(self.SPEC, "// reworked design spec\n")
        self.assertTrue(self._facts().in_review)

    def test_committed_spec_is_not_in_review(self) -> None:
        self._design(self.EPOCH + 60)
        self.assertFalse(self._facts().in_review)

    def test_designed_is_the_last_commit_of_the_spec(self) -> None:
        sha = self._design(self.EPOCH + 60)
        self._write(self.README, "# Demo\n")
        self._commit("document the role", self.EPOCH + 120)
        self.assertEqual(
            self._facts().designed, DesignCommit(sha=sha, timestamp=self.EPOCH + 60)
        )

    def test_removed_spec_counts_as_never_designed(self) -> None:
        self._design(self.EPOCH + 60)
        (self.root / self.SPEC).unlink()
        self._commit("drop the design spec", self.EPOCH + 120)
        self.assertIsNone(self._facts().designed)

    def test_base_commit_after_the_design_pass_is_a_base_change(self) -> None:
        self._design(self.EPOCH + 60)
        self._move_base(self.EPOCH + 120)
        self.assertTrue(self._facts().base_changed)

    def test_base_commit_before_the_design_pass_is_no_base_change(self) -> None:
        self._move_base(self.EPOCH + 60)
        self._design(self.EPOCH + 120)
        self.assertFalse(self._facts().base_changed)

    def test_base_commit_in_the_second_of_the_design_pass_is_a_base_change(
        self,
    ) -> None:
        self._design(self.EPOCH + 60)
        self._move_base(self.EPOCH + 60)
        self.assertTrue(self._facts().base_changed)

    def test_version_bump_since_the_design_pass_is_measured(self) -> None:
        self._design(self.EPOCH + 60)
        self._declare(self.ROLE, "3.1.0")
        facts = self._facts()
        self.assertEqual(
            (facts.designed_version, facts.current_version, facts.version_gap),
            ("1.0.0", "3.1.0", (2, 1, 0)),
        )

    def test_commit_times_span_the_role_history(self) -> None:
        self._write(self.README, "# Demo\n")
        self._commit("document the role", self.EPOCH + 60)
        facts = self._facts()
        self.assertEqual((facts.created, facts.changed), (self.EPOCH, self.EPOCH + 60))

    def test_commit_outside_the_role_keeps_its_change_time(self) -> None:
        self._move_base(self.EPOCH + 60)
        self.assertEqual(self._facts().changed, self.EPOCH)

    def test_role_without_commit_has_no_commit_times(self) -> None:
        self._declare("web-app-draft", "1.0.0")
        draft = self._facts_of("web-app-draft")
        self.assertEqual((draft.created, draft.changed), (None, None))

    def test_oldest_commit_is_found_behind_a_merge_of_parallel_histories(self) -> None:
        self._git("checkout", "--quiet", "-b", "side")
        self._declare("web-app-twin", "1.0.0")
        self._commit("add the twin role on the side branch", self.EPOCH + 60)
        self._git("checkout", "--quiet", "main")
        self._declare("web-app-twin", "1.0.0")
        self._commit("add the twin role on main", self.EPOCH + 120)
        self._git(
            "merge",
            "--quiet",
            "--no-ff",
            "--message",
            "merge the side branch",
            "side",
            **self._dated(self.EPOCH + 180),
        )
        self.assertEqual(self._facts_of("web-app-twin").created, self.EPOCH + 60)

    def test_collecting_facts_leaves_the_index_untouched(self) -> None:
        self._design(self.EPOCH + 60)
        os.utime(self.root / self.SPEC, (self.EPOCH, self.EPOCH))
        index = self._index()
        self._facts()
        self.assertEqual(self._index(), index)


class TestRepositoryRoot(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        _isolate_git(self)

    def test_subdirectory_resolves_to_the_work_tree_root(self) -> None:
        subprocess.run(
            ["git", "init", "--quiet", "-b", "main"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        nested = self.root / "roles" / "web-app-demo"
        nested.mkdir(parents=True)
        self.assertEqual(repository_root(nested), self.root)

    def test_directory_outside_a_work_tree_raises_git_error(self) -> None:
        ceiling = {"GIT_CEILING_DIRECTORIES": str(self.root.parent)}
        with patch.dict(os.environ, ceiling), self.assertRaises(GitError):
            repository_root(self.root)

    def test_missing_git_binary_raises_git_error(self) -> None:
        with (
            patch(
                "cli.meta.roles.design.subprocess.run",
                side_effect=FileNotFoundError("git"),
            ),
            self.assertRaises(GitError),
        ):
            repository_root(self.root)


class TestCLIMain(unittest.TestCase):
    FACTS: ClassVar[list[RoleFacts]] = [
        replace(DESIGNED, role="web-app-stale", current_version="2.0.0"),
        replace(NEVER_DESIGNED, role="web-app-review", in_review=True),
        DESIGNED,
        NEVER_DESIGNED,
    ]

    def _run(self, argv: list[str], facts: list[RoleFacts]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch(
                "cli.meta.roles.design.__main__.repository_root",
                return_value=Path("/repo"),
            ),
            patch("cli.meta.roles.design.__main__.collect_facts", return_value=facts),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = cli_main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_next_prints_nothing_when_no_role_is_due(self) -> None:
        self.assertEqual(self._run(["--next"], [DESIGNED]), (0, "", ""))

    def test_next_prints_the_first_due_role(self) -> None:
        self.assertEqual(self._run(["--next"], self.FACTS), (0, "web-app-fresh\n", ""))

    def test_table_lists_the_due_queue_and_the_summary(self) -> None:
        _, out, _ = self._run([], self.FACTS)
        self.assertEqual(
            out.splitlines(),
            [
                "rank  role           state  reason",
                "1     web-app-fresh  new    never designed",
                "2     web-app-stale  stale  version 1.0.0 -> 2.0.0",
                "",
                "due: 2, in review: 1, current: 1",
            ],
        )

    def test_all_appends_the_roles_that_are_not_due(self) -> None:
        _, out, _ = self._run(["--all"], self.FACTS)
        self.assertEqual(
            out.splitlines()[3:5],
            [
                "      web-app-review    review   design spec awaits approval",
                "      web-app-designed  current  up to date",
            ],
        )

    def test_json_emits_the_queue_fields(self) -> None:
        stale = replace(DESIGNED, role="web-app-stale", current_version="2.1.0")
        _, out, _ = self._run(["--format", "json"], [stale])
        self.assertEqual(
            json.loads(out),
            [
                {
                    "rank": 1,
                    "role": "web-app-stale",
                    "state": "stale",
                    "reason": "version 1.0.0 -> 2.1.0",
                    "version_gap": [1, 1, 0],
                    "created": 100,
                    "changed": 100,
                }
            ],
        )

    def test_git_failure_exits_non_zero_with_a_message(self) -> None:
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch(
                "cli.meta.roles.design.__main__.repository_root",
                side_effect=GitError("cannot run git"),
            ),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = cli_main([])
        self.assertEqual((code, out.getvalue()), (1, ""))
        self.assertIn("cannot run git", err.getvalue())


if __name__ == "__main__":
    unittest.main()
