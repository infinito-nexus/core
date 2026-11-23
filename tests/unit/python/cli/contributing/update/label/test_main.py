from __future__ import annotations

import io
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import cli.contributing.update.label.__main__ as label_main
from utils.update.level import LEVELS

REPO = "infinito-nexus/core"
UPDATE = label_main.UPDATE.name
MAJOR = label_main.MAJOR.name
MINOR = label_main.MINOR.name
PATCH = label_main.PATCH.name


class FakeGh:
    """Answers the label reads and records every write.

    Args:
        repository: label names the repository has.
        pull_request: label names pull request 4 carries.
        racing: names whose create fails because a parallel run made them.
    """

    def __init__(self, repository, pull_request, racing=()):
        self.repository = set(repository)
        self.pull_request = set(pull_request)
        self.racing = set(racing)
        self.writes = []

    def __call__(self, args):
        if args[:2] == ["api", "--paginate"]:
            names = self.pull_request if "/issues/" in args[2] else self.repository
            return "".join(f"{name}\n" for name in sorted(names))
        self.writes.append(list(args))
        if args[:2] == ["label", "create"] and args[2] in self.racing:
            self.repository.add(args[2])
            raise subprocess.CalledProcessError(1, ["gh", *args])
        return ""


class TestLevel(unittest.TestCase):
    def test_semver_levels_map_to_their_label(self):
        self.assertEqual(
            [
                label_main.level(f"version-update:semver-{name}").name
                for name in ("major", "minor", "patch")
            ],
            [MAJOR, MINOR, PATCH],
        )

    def test_an_unknown_or_empty_type_counts_as_major(self):
        self.assertEqual(
            {label_main.level(kind).name for kind in ("", "security", "semver-minor")},
            {MAJOR},
        )

    def test_every_level_the_updater_prints_has_a_label(self):
        self.assertEqual(set(label_main.LEVEL_OF_NAME), set(LEVELS))

    def test_every_label_name_carries_an_emoji_before_its_word(self):
        for label in (label_main.UPDATE, *label_main.LEVELS):
            with self.subTest(label=label.name):
                mark, _, word = label.name.partition(" ")
                self.assertFalse(mark.isascii())
                self.assertTrue(word.isascii() and word)


class TestSync(unittest.TestCase):
    def test_a_bare_pull_request_gets_update_and_its_level(self):
        gh = FakeGh({UPDATE, MINOR}, set())
        actions = label_main.sync(gh, REPO, 4, label_main.MINOR)
        self.assertEqual(actions, [f"added {UPDATE}, {MINOR}"])
        self.assertEqual(
            gh.writes,
            [
                [
                    "api",
                    "--method",
                    "POST",
                    f"repos/{REPO}/issues/4/labels",
                    "-f",
                    f"labels[]={UPDATE}",
                    "-f",
                    f"labels[]={MINOR}",
                ]
            ],
        )

    def test_labels_already_present_cause_no_write(self):
        gh = FakeGh({UPDATE, PATCH}, {UPDATE, PATCH, "dependencies"})
        self.assertEqual(label_main.sync(gh, REPO, 4, label_main.PATCH), [])
        self.assertEqual(gh.writes, [])

    def test_a_stale_level_is_removed(self):
        gh = FakeGh({UPDATE, MAJOR, MINOR}, {UPDATE, MINOR})
        actions = label_main.sync(gh, REPO, 4, label_main.MAJOR)
        self.assertEqual(actions, [f"removed {MINOR}", f"added {MAJOR}"])

    def test_missing_repository_labels_are_created_first(self):
        gh = FakeGh(set(), set())
        label_main.sync(gh, REPO, 4, label_main.PATCH)
        created = [write[2] for write in gh.writes if write[:2] == ["label", "create"]]
        self.assertEqual(created, [UPDATE, PATCH])

    def test_a_label_a_parallel_run_created_counts_as_done(self):
        gh = FakeGh({PATCH}, set(), racing={UPDATE})
        actions = label_main.sync(gh, REPO, 4, label_main.PATCH)
        self.assertEqual(actions, [f"added {UPDATE}, {PATCH}"])

    def test_a_create_failure_that_leaves_the_label_missing_raises(self):
        gh = FakeGh(set(), set())

        def failing(args):
            if args[:2] == ["label", "create"]:
                raise subprocess.CalledProcessError(1, ["gh", *args])
            return gh(args)

        with self.assertRaises(subprocess.CalledProcessError):
            label_main.sync(failing, REPO, 4, label_main.MAJOR)


class TestMain(unittest.TestCase):
    def test_main_reports_when_nothing_changes(self):
        gh = FakeGh({UPDATE, MAJOR}, {UPDATE, MAJOR})
        out = io.StringIO()
        with patch.object(label_main, "run_gh", gh), redirect_stdout(out):
            code = label_main.main(["--repo", REPO, "--pr", "4", "--update-type", ""])
        self.assertEqual((code, out.getvalue()), (0, "#4 already carries its labels\n"))

    def test_ensure_only_creates_the_missing_labels_and_touches_no_pr(self):
        gh = FakeGh({UPDATE, MINOR}, set())
        out = io.StringIO()
        with patch.object(label_main, "run_gh", gh), redirect_stdout(out):
            code = label_main.main(["--repo", REPO, "--ensure-only"])
        created = [w[2] for w in gh.writes if w[:2] == ["label", "create"]]
        self.assertEqual((code, created), (0, [MAJOR, PATCH]))
        self.assertEqual(len(gh.writes), 2)

    def test_without_ensure_only_the_pr_and_type_are_required(self):
        with self.assertRaises(SystemExit) as raised, redirect_stdout(io.StringIO()):
            label_main.main(["--repo", REPO, "--pr", "4"])
        self.assertEqual(raised.exception.code, 2)

    def test_the_level_labels_an_updater_pull_request(self):
        gh = FakeGh({UPDATE, MINOR, PATCH}, {UPDATE, PATCH})
        out = io.StringIO()
        with patch.object(label_main, "run_gh", gh), redirect_stdout(out):
            code = label_main.main(["--repo", REPO, "--pr", "4", "--level", "minor"])
        self.assertEqual(
            (code, out.getvalue()), (0, f"removed {PATCH}\nadded {MINOR}\n")
        )

    def test_a_level_and_an_update_type_together_are_refused(self):
        with self.assertRaises(SystemExit) as raised, redirect_stdout(io.StringIO()):
            label_main.main(
                ["--repo", REPO, "--pr", "4", "--level", "minor", "--update-type", ""]
            )
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
