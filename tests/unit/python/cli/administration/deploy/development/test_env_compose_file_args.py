from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.deploy.development.env import (
    INFRA_CONSUMER,
    compose_file_args,
)
from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml

_LOCAL_PRIMARY = {
    "GITHUB_ACTIONS": "",
    "INFINITO_RUNNING_ON_GITHUB": "",
    "CI": "",
    "INFINITO_INSTANCE": "0",
    "INFINITO_GIT_COMMON_DIR": "",
    "INFINITO_CACHE_STACK": "",
    "INFINITO_POOL_RUNNER": "",
    "INFINITO_CACHE_SHARED_HOST_PATH": "",
    "INFINITO_CACHE_HOST_PACMAN_PATH": "",
    "INFINITO_GHCR_MIRROR": "",
    "INFINITO_PUBLISH_PORTS": "",
    "INFINITO_GPU_COUNT": "0",
    "INFINITO_EXTRA_MOUNTS": "",
}

_SHARED = "/var/cache/infinito/core/cache/shared"
_HOST_PACMAN = "/var/cache/pacman/pkg"

_WORKTREE = {
    **_LOCAL_PRIMARY,
    "INFINITO_INSTANCE": "2",
    "INFINITO_GIT_COMMON_DIR": "/repo/.git",
}

_REMOVED = (
    "compose/cache.override.yml",
    "compose/cache.shared.override.yml",
    "compose/tools.override.yml",
)

_FORBIDDEN = frozenset(
    {"registry-cache", "package-cache", "package-cache-frontend", "tools"}
)


def _cache_or_tools_services(docs: dict[str, dict]) -> set[str]:
    """Args:
        docs: compose file name to its loaded content.

    Returns:
        ``file:service`` for every cache or tools service a checkout file defines.
    """
    return {
        f"{name}:{service}"
        for name, doc in docs.items()
        for service in doc.get("services") or {}
        if service in _FORBIDDEN
    }


class TestComposeFileArgs(unittest.TestCase):
    @patch.dict(os.environ, _LOCAL_PRIMARY, clear=False)
    def test_the_primary_checkout_joins_the_infra_network(self) -> None:
        self.assertEqual(
            compose_file_args(), ["-f", "compose.yml", "-f", INFRA_CONSUMER]
        )

    @patch.dict(os.environ, _WORKTREE, clear=False)
    def test_a_worktree_joins_the_same_infra_network(self) -> None:
        self.assertEqual(
            compose_file_args(),
            [
                "-f",
                "compose.yml",
                "-f",
                "compose/worktree.override.yml",
                "-f",
                INFRA_CONSUMER,
            ],
        )

    @patch.dict(os.environ, {**_LOCAL_PRIMARY, "INFINITO_INSTANCE": "5"}, clear=False)
    def test_a_stray_slot_alone_changes_nothing(self) -> None:
        self.assertEqual(
            compose_file_args(), ["-f", "compose.yml", "-f", INFRA_CONSUMER]
        )

    @patch.dict(os.environ, {**_WORKTREE, "CI": "true"}, clear=False)
    def test_ci_keeps_the_git_mount_but_joins_no_infra_network(self) -> None:
        self.assertEqual(
            compose_file_args(),
            ["-f", "compose.yml", "-f", "compose/worktree.override.yml"],
        )

    @patch.dict(os.environ, {**_LOCAL_PRIMARY, "INFINITO_CACHE_STACK": "false"})
    def test_a_disabled_cache_stack_attaches_to_no_infra_network(self) -> None:
        self.assertEqual(compose_file_args(), ["-f", "compose.yml"])

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
                INFRA_CONSUMER,
                "-f",
                "compose/shared-cache.override.yml",
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
            compose_file_args()[-4:],
            [
                "-f",
                "compose/shared-cache.override.yml",
                "-f",
                "compose/pacman.override.yml",
            ],
        )

    @patch.dict(
        os.environ,
        {**_LOCAL_PRIMARY, "INFINITO_CACHE_HOST_PACMAN_PATH": _HOST_PACMAN},
        clear=False,
    )
    def test_a_host_pacman_cache_needs_the_shared_folder(self) -> None:
        self.assertNotIn("compose/pacman.override.yml", compose_file_args())

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
        self.assertEqual(compose_file_args(), ["-f", "compose.yml"])

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


class TestNoCheckoutCacheOrToolsService(unittest.TestCase):
    def test_the_checkout_overrides_are_gone(self) -> None:
        for relative in _REMOVED:
            self.assertFalse((PROJECT_ROOT / relative).exists(), relative)

    def test_no_checkout_compose_file_defines_a_cache_or_tools_service(self) -> None:
        files = [
            PROJECT_ROOT / "compose.yml",
            *(PROJECT_ROOT / "compose").glob("*.override.yml"),
        ]
        docs = {path.name: load_yaml(path) or {} for path in files}
        self.assertEqual(_cache_or_tools_services(docs), set())

    def test_a_planted_cache_service_would_be_found(self) -> None:
        docs = {"planted.override.yml": {"services": {"registry-cache": {}}}}
        self.assertEqual(
            _cache_or_tools_services(docs), {"planted.override.yml:registry-cache"}
        )

    def test_the_consumer_override_joins_the_external_infra_network(self) -> None:
        override = load_yaml(PROJECT_ROOT / INFRA_CONSUMER)
        self.assertEqual(
            override["networks"]["infra"], {"external": True, "name": "infinito-infra"}
        )
        self.assertIn("infra", override["services"]["infinito"]["networks"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
