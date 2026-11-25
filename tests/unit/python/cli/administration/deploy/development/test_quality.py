from __future__ import annotations

import argparse
import unittest
import unittest.mock

from cli.administration.deploy.development import quality
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml

COMPOSE = PROJECT_ROOT / "compose.yml"
WORKTREE_OVERRIDE = PROJECT_ROOT / "compose" / "worktree.override.yml"


def _compose(returncode: int) -> unittest.mock.Mock:
    compose = unittest.mock.Mock()
    compose.run.return_value.returncode = returncode
    return compose


class TestDevelopmentQuality(unittest.TestCase):
    def _handle(self, argv: list[str], compose: unittest.mock.Mock) -> int:
        with unittest.mock.patch(
            "cli.administration.deploy.development.quality.make_compose",
            return_value=compose,
        ):
            return quality.handler(argparse.Namespace(args=argv))

    def test_runs_the_tools_profile_service_with_the_given_arguments(self):
        compose = _compose(0)
        self.assertEqual(self._handle(["--", "check", "--staged"], compose), 0)
        compose.run.assert_called_once_with(
            ["--profile", "tools", "run", "--rm", "quality", "check", "--staged"],
            check=False,
        )

    def test_returns_the_exit_code_of_quality(self):
        self.assertEqual(self._handle(["check", "--staged"], _compose(1)), 1)

    def test_refuses_to_run_without_arguments(self):
        compose = _compose(0)
        with self.assertRaises(SystemExit):
            self._handle(["--"], compose)
        compose.run.assert_not_called()

    def test_the_parser_hands_everything_after_the_separator_to_quality(self):
        parser = argparse.ArgumentParser()
        quality.add_parser(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["quality", "--", "check", "--base", "main"])
        self.assertEqual(args.args, ["--", "check", "--base", "main"])
        self.assertIs(args._handler, quality.handler)


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

    def test_the_image_is_pinned_by_tag_and_digest(self):
        self.assertRegex(
            self.service["image"],
            r"^ghcr\.io/infinito-nexus/quality:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$",
        )

    def test_a_worktree_mounts_its_git_directory_read_only(self):
        override = load_yaml(WORKTREE_OVERRIDE)
        (mount,) = override["services"]["quality"]["volumes"]
        self.assertTrue(mount.endswith(":ro"))
        self.assertEqual(mount.count("INFINITO_GIT_COMMON_DIR"), 2)


if __name__ == "__main__":
    unittest.main()
