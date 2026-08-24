"""Unit tests for compose_file_args.

Pins which override files each runtime context layers on compose.yml. Every
override is gated on the resource it needs rather than on the instance slot,
because an unsatisfied `:?` guard inside one of them aborts the whole stack.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cli.administration.deploy.development.env import compose_file_args

_LOCAL_PRIMARY = {
    "GITHUB_ACTIONS": "",
    "INFINITO_RUNNING_ON_GITHUB": "",
    "CI": "",
    "INFINITO_INSTANCE": "0",
    "INFINITO_GIT_COMMON_DIR": "",
    "INFINITO_CACHE_NETWORK": "",
    "INFINITO_CACHE_STACK": "",
    "INFINITO_PUBLISH_PORTS": "",
}

_WORKTREE = {
    **_LOCAL_PRIMARY,
    "INFINITO_INSTANCE": "2",
    "INFINITO_GIT_COMMON_DIR": "/repo/.git",
    "INFINITO_CACHE_NETWORK": "primary_default",
}


class TestComposeFileArgs(unittest.TestCase):
    @patch.dict(os.environ, _LOCAL_PRIMARY, clear=False)
    def test_primary_instance_loads_the_cache_stack(self) -> None:
        self.assertEqual(
            compose_file_args(),
            ["-f", "compose.yml", "-f", "compose/cache.override.yml"],
        )

    @patch.dict(os.environ, _WORKTREE, clear=False)
    def test_worktree_adds_the_git_and_shared_cache_overrides(self) -> None:
        self.assertEqual(
            compose_file_args(),
            [
                "-f",
                "compose.yml",
                "-f",
                "compose/worktree.override.yml",
                "-f",
                "compose/cache.override.yml",
                "-f",
                "compose/cache.shared.override.yml",
            ],
        )

    @patch.dict(os.environ, {**_LOCAL_PRIMARY, "INFINITO_INSTANCE": "5"}, clear=False)
    def test_a_stray_slot_alone_changes_nothing(self) -> None:
        self.assertEqual(
            compose_file_args(),
            ["-f", "compose.yml", "-f", "compose/cache.override.yml"],
        )

    @patch.dict(os.environ, {**_LOCAL_PRIMARY, "INFINITO_GIT_COMMON_DIR": "/repo/.git"})
    def test_a_shared_git_dir_alone_adds_only_the_worktree_override(self) -> None:
        self.assertEqual(
            compose_file_args(),
            [
                "-f",
                "compose.yml",
                "-f",
                "compose/worktree.override.yml",
                "-f",
                "compose/cache.override.yml",
            ],
        )

    @patch.dict(os.environ, {**_WORKTREE, "CI": "true"}, clear=False)
    def test_ci_keeps_the_git_mount_but_drops_every_cache_override(self) -> None:
        self.assertEqual(
            compose_file_args(),
            ["-f", "compose.yml", "-f", "compose/worktree.override.yml"],
        )

    @patch.dict(os.environ, {**_LOCAL_PRIMARY, "CI": "true"}, clear=False)
    def test_ci_loads_no_override_at_all(self) -> None:
        self.assertEqual(compose_file_args(), ["-f", "compose.yml"])

    @patch.dict(
        os.environ,
        {**_LOCAL_PRIMARY, "INFINITO_PUBLISH_PORTS": "false"},
        clear=False,
    )
    def test_unpublished_ports_append_the_noports_override(self) -> None:
        self.assertEqual(
            compose_file_args()[-2:], ["-f", "compose/noports.override.yml"]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
