"""Unit tests for compose_file_args.

Pins which override files each runtime context layers on compose.yml. Every
override is gated on the resource it needs rather than on the instance slot,
because an unsatisfied `:?` guard inside one of them aborts the whole stack.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.deploy.development.env import (
    TOOLS_LANE_KEYS,
    compose_file_args,
)
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text

_LOCAL_PRIMARY = {
    "GITHUB_ACTIONS": "",
    "INFINITO_RUNNING_ON_GITHUB": "",
    "CI": "",
    "INFINITO_INSTANCE": "0",
    "INFINITO_GIT_COMMON_DIR": "",
    "INFINITO_CACHE_NETWORK": "",
    "INFINITO_CACHE_STACK": "",
    "INFINITO_CACHE_SHARED_HOST_PATH": "",
    "INFINITO_CACHE_HOST_PACMAN_PATH": "",
    "INFINITO_GHCR_MIRROR": "",
    "INFINITO_PUBLISH_PORTS": "",
    "INFINITO_GPU_COUNT": "0",
    "INFINITO_TOOLS_LIBRETRANSLATE_PORT": "8097",
    "INFINITO_TOOLS_LITELLM_PORT": "8081",
    "INFINITO_TOOLS_MODELS_HOST_PATH": "/var/cache/infinito/core/cache/models",
    "INFINITO_TOOLS_S1_PORT": "8096",
    "INFINITO_TOOLS_TRANSLATE_PORT": "8101",
    "INFINITO_EXTRA_MOUNTS": "",
}

_SHARED = "/var/cache/infinito/core/cache/shared"
_HOST_PACMAN = "/var/cache/pacman/pkg"

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
        {**_LOCAL_PRIMARY, "INFINITO_CACHE_SHARED_HOST_PATH": _SHARED},
        clear=False,
    )
    def test_a_shared_cache_folder_adds_its_mount(self) -> None:
        self.assertEqual(
            compose_file_args(),
            [
                "-f",
                "compose.yml",
                "-f",
                "compose/cache.override.yml",
                "-f",
                "compose/shared-cache.override.yml",
                "-f",
                "compose/tools.override.yml",
            ],
        )

    @patch.dict(
        os.environ,
        {
            **_LOCAL_PRIMARY,
            "INFINITO_CACHE_SHARED_HOST_PATH": _SHARED,
            "INFINITO_CACHE_HOST_PACMAN_PATH": _HOST_PACMAN,
        },
        clear=False,
    )
    def test_a_host_pacman_cache_adds_its_read_only_mount(self) -> None:
        self.assertEqual(
            compose_file_args(),
            [
                "-f",
                "compose.yml",
                "-f",
                "compose/cache.override.yml",
                "-f",
                "compose/shared-cache.override.yml",
                "-f",
                "compose/pacman.override.yml",
                "-f",
                "compose/tools.override.yml",
            ],
        )

    @patch.dict(
        os.environ,
        {**_LOCAL_PRIMARY, "INFINITO_CACHE_HOST_PACMAN_PATH": _HOST_PACMAN},
        clear=False,
    )
    def test_a_host_pacman_cache_needs_the_shared_folder(self) -> None:
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

    @patch.dict(
        os.environ,
        {
            **_LOCAL_PRIMARY,
            "CI": "true",
            "INFINITO_CACHE_SHARED_HOST_PATH": _SHARED,
            "INFINITO_CACHE_HOST_PACMAN_PATH": _HOST_PACMAN,
        },
        clear=False,
    )
    def test_the_cache_folders_stay_out_without_the_cache_stack(self) -> None:
        self.assertEqual(
            compose_file_args(),
            ["-f", "compose.yml", "-f", "compose/tools.override.yml"],
        )

    def test_an_env_without_the_cache_keys_layers_neither_override(self) -> None:
        stale = {
            k: v
            for k, v in _LOCAL_PRIMARY.items()
            if k
            not in (
                "INFINITO_CACHE_SHARED_HOST_PATH",
                "INFINITO_CACHE_HOST_PACMAN_PATH",
            )
        }
        with patch.dict(os.environ, stale, clear=False):
            os.environ.pop("INFINITO_CACHE_SHARED_HOST_PATH", None)
            os.environ.pop("INFINITO_CACHE_HOST_PACMAN_PATH", None)
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

    def test_extra_mounts_append_their_generated_override(self) -> None:
        with (
            tempfile.TemporaryDirectory() as mount,
            patch.dict(
                os.environ,
                {**_LOCAL_PRIMARY, "INFINITO_EXTRA_MOUNTS": mount},
                clear=False,
            ),
            patch(
                "cli.administration.deploy.development.extra_mounts.write_mounts_override",
                return_value="build/compose/extra-mounts.override.yml",
            ) as write,
        ):
            args = compose_file_args()
            self.assertEqual(write.call_args.args[1], [Path(mount)])
        self.assertEqual(args[-2:], ["-f", "build/compose/extra-mounts.override.yml"])

    def test_an_entry_that_is_no_directory_stops_the_stack_naming_it(self) -> None:
        with (
            patch.dict(
                os.environ,
                {**_LOCAL_PRIMARY, "INFINITO_EXTRA_MOUNTS": "/nonexistent/gui"},
                clear=False,
            ),
            self.assertRaises(SystemExit) as ctx,
        ):
            compose_file_args()
        self.assertIn("/nonexistent/gui", str(ctx.exception.code))


class TestToolsLaneGateCoversItsGuards(unittest.TestCase):
    def test_every_guard_the_override_adds_is_gated(self) -> None:
        """A `:?` guard the gate does not know aborts every compose call.

        The guards compose.yml already carries are satisfied for any stack
        that runs at all, so only the ones the lane's override adds on top
        can fire against an .env that predates them. INFINITO_IMAGE is the
        one exception: the deploy CLI injects it into the process
        environment and it never reaches .env, so gating on it would drop
        the lane permanently.
        """
        guards = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):\?")
        shared = set(guards.findall(read_text(PROJECT_ROOT / "compose.yml")))
        override = set(
            guards.findall(read_text(PROJECT_ROOT / "compose" / "tools.override.yml"))
        )
        added = override - shared - {"INFINITO_IMAGE"}
        self.assertEqual(
            sorted(added - set(TOOLS_LANE_KEYS)),
            [],
            "compose/tools.override.yml guards these variables, and "
            "compose_file_args layers the file in without checking them, so "
            "an .env written before they existed aborts every compose "
            "command instead of only dropping the lane. Add them to "
            "TOOLS_LANE_KEYS.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
