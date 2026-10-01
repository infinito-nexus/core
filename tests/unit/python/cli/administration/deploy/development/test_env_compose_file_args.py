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
    "INFINITO_GPU_COUNT": "0",
    "INFINITO_TOOLS_LIBRETRANSLATE_PORT": "8097",
    "INFINITO_TOOLS_MODELS_HOST_PATH": "/var/cache/infinito/core/cache/models",
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
            [
                "-f",
                "compose.yml",
                "-f",
                "compose/cache.override.yml",
                "-f",
                "compose/tools.override.yml",
            ],
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
                "-f",
                "compose/tools.override.yml",
            ],
        )

    @patch.dict(os.environ, {**_LOCAL_PRIMARY, "INFINITO_INSTANCE": "5"}, clear=False)
    def test_a_stray_slot_alone_changes_nothing(self) -> None:
        self.assertEqual(
            compose_file_args(),
            [
                "-f",
                "compose.yml",
                "-f",
                "compose/cache.override.yml",
                "-f",
                "compose/tools.override.yml",
            ],
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
                "-f",
                "compose/tools.override.yml",
            ],
        )

    @patch.dict(os.environ, {**_WORKTREE, "CI": "true"}, clear=False)
    def test_ci_keeps_the_git_mount_but_drops_every_cache_override(self) -> None:
        self.assertEqual(
            compose_file_args(),
            [
                "-f",
                "compose.yml",
                "-f",
                "compose/worktree.override.yml",
                "-f",
                "compose/tools.override.yml",
            ],
        )

    @patch.dict(os.environ, {**_LOCAL_PRIMARY, "CI": "true"}, clear=False)
    def test_ci_loads_no_override_at_all(self) -> None:
        self.assertEqual(
            compose_file_args(),
            ["-f", "compose.yml", "-f", "compose/tools.override.yml"],
        )

    @patch.dict(
        os.environ,
        {**_LOCAL_PRIMARY, "INFINITO_PUBLISH_PORTS": "false"},
        clear=False,
    )
    def test_unpublished_ports_add_the_noports_override(self) -> None:
        self.assertIn("compose/noports.override.yml", compose_file_args())

    @patch.dict(os.environ, _LOCAL_PRIMARY, clear=False)
    def test_a_host_without_a_gpu_reserves_none(self) -> None:
        self.assertNotIn("compose/gpu.override.yml", compose_file_args())

    @patch.dict(
        os.environ,
        {**_LOCAL_PRIMARY, "INFINITO_GPU_COUNT": "all"},
        clear=False,
    )
    def test_a_host_with_a_gpu_adds_the_reservation(self) -> None:
        self.assertIn("compose/gpu.override.yml", compose_file_args())

    @patch.dict(
        os.environ,
        {**_LOCAL_PRIMARY, "INFINITO_TOOLS_LIBRETRANSLATE_PORT": ""},
        clear=False,
    )
    def test_a_stale_env_drops_the_tools_lane_instead_of_aborting(self) -> None:
        """The lane's override carries `:?` guards, which fire even behind its
        profile, so layering it in against an .env that predates those keys
        would abort every compose command rather than only the lane."""
        self.assertNotIn("compose/tools.override.yml", compose_file_args())

    @patch.dict(
        os.environ,
        {**_LOCAL_PRIMARY, "INFINITO_TOOLS_MODELS_HOST_PATH": ""},
        clear=False,
    )
    def test_the_models_path_gates_the_tools_lane_too(self) -> None:
        self.assertNotIn("compose/tools.override.yml", compose_file_args())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
