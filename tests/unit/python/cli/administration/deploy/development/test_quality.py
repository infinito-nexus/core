from __future__ import annotations

import argparse
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from cli.administration.deploy.development import quality
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml

COMPOSE = PROJECT_ROOT / "compose.yml"
WORKTREE_OVERRIDE = PROJECT_ROOT / "compose" / "worktree.override.yml"


def _compose(returncode: int) -> unittest.mock.Mock:
    compose = unittest.mock.Mock()
    compose.run.return_value.returncode = returncode
    return compose


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestDevelopmentQuality(unittest.TestCase):
    def _handle(
        self, argv: list[str], compose: unittest.mock.Mock, mounts: list[str]
    ) -> int:
        with (
            unittest.mock.patch(
                "cli.administration.deploy.development.quality.make_compose",
                return_value=compose,
            ),
            unittest.mock.patch(
                "cli.administration.deploy.development.quality.git_mounts",
                return_value=mounts,
            ),
        ):
            return quality.handler(argparse.Namespace(args=argv))

    def test_runs_the_tools_profile_service_with_the_given_arguments(self):
        compose = _compose(0)
        self.assertEqual(self._handle(["--", "check", "--staged"], compose, []), 0)
        compose.run.assert_called_once_with(
            ["--profile", "tools", "run", "--rm", "quality", "check", "--staged"],
            check=False,
        )

    def test_binds_the_git_directories_before_the_service(self):
        compose = _compose(0)
        mounts = ["/repo/.git:/repo/.git:ro", "/objects:/objects:ro"]
        self._handle(["check", "--base", "origin/main"], compose, mounts)
        compose.run.assert_called_once_with(
            [
                "--profile",
                "tools",
                "run",
                "--rm",
                "-v",
                "/repo/.git:/repo/.git:ro",
                "-v",
                "/objects:/objects:ro",
                "quality",
                "check",
                "--base",
                "origin/main",
            ],
            check=False,
        )

    def test_returns_the_exit_code_of_quality(self):
        self.assertEqual(self._handle(["check", "--staged"], _compose(1), []), 1)

    def test_refuses_to_run_without_arguments(self):
        compose = _compose(0)
        with self.assertRaises(SystemExit):
            self._handle(["--"], compose, [])
        compose.run.assert_not_called()

    def test_the_parser_hands_everything_after_the_separator_to_quality(self):
        parser = argparse.ArgumentParser()
        quality.add_parser(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["quality", "--", "check", "--base", "main"])
        self.assertEqual(args.args, ["--", "check", "--base", "main"])
        self.assertIs(args._handler, quality.handler)


class TestGitMounts(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.base = Path(scratch.name).resolve()
        self.main_git = self.base / "main" / ".git"
        self.borrowed = self.main_git / "objects"
        self.borrowed.mkdir(parents=True)
        self.checkout = self.base / "checkout"
        self.checkout.mkdir()
        self.own_objects = self.checkout / ".git" / "objects"

    def test_a_primary_clone_needs_no_bind(self):
        self.own_objects.mkdir(parents=True)
        self.assertEqual(quality.git_mounts(self.checkout), [])

    def test_a_linked_worktree_binds_its_common_directory_once(self):
        gitdir = self.main_git / "worktrees" / "checkout"
        _write(self.checkout / ".git", f"gitdir: {gitdir}\n")
        _write(gitdir / "commondir", "../..\n")
        mounts = quality.git_mounts(self.checkout)
        self.assertEqual(mounts, [f"{self.main_git}:{self.main_git}:ro"])

    def test_a_shared_clone_binds_the_object_directory_it_borrows(self):
        _write(self.own_objects / "info" / "alternates", f"{self.borrowed}\n")
        mounts = quality.git_mounts(self.checkout)
        self.assertEqual(mounts, [f"{self.borrowed}:{self.borrowed}:ro"])

    def test_alternates_are_followed_relative_to_the_listing_directory(self):
        origin = self.base / "origin" / "objects"
        origin.mkdir(parents=True)
        _write(self.borrowed / "info" / "alternates", "../../../origin/objects\n")
        _write(
            self.own_objects / "info" / "alternates",
            f"# borrowed\n{self.borrowed}\n",
        )
        mounts = quality.git_mounts(self.checkout)
        self.assertEqual(
            mounts,
            [f"{origin}:{origin}:ro", f"{self.borrowed}:{self.borrowed}:ro"],
        )


class TestQualityComposeService(unittest.TestCase):
    def setUp(self):
        self.service = load_yaml(COMPOSE)["services"]["quality"]

    def test_the_service_only_starts_under_the_tools_profile(self):
        self.assertEqual(self.service["profiles"], ["tools"])

    def test_the_service_runs_without_network_as_nobody_on_a_read_only_tree(self):
        self.assertEqual(self.service["network_mode"], "none")
        self.assertIs(self.service["read_only"], True)
        self.assertEqual(self.service["user"], "65534")
        self.assertEqual(self.service["volumes"], [".:/src:ro"])

    def test_the_image_is_pinned_by_tag_and_digest(self):  # nocheck: test.text-presence -- matches the image value of the parsed compose service  # fmt: skip
        self.assertRegex(
            self.service["image"],
            r"^ghcr\.io/infinito-nexus/quality:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$",
        )

    def test_the_worktree_override_leaves_the_git_binds_to_the_handler(self):
        self.assertNotIn("quality", load_yaml(WORKTREE_OVERRIDE)["services"])


if __name__ == "__main__":
    unittest.main()
