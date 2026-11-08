# tests/cli/administration/deploy/development/test_compose.py
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.compose import Compose
from utils.cache import pin


class TestComposeUpRetries(unittest.TestCase):
    def _compose(self) -> Compose:
        return Compose(repo_root=Path("/tmp/infinito-nexus"), distro="arch")

    @patch("time.sleep", autospec=True)
    def test_compose_up_with_retries_succeeds_after_transient_failures(
        self, sleep_mock: MagicMock
    ) -> None:
        compose = self._compose()

        compose.run = MagicMock(
            side_effect=[
                subprocess.CalledProcessError(1, ["docker", "compose"], "out1", "err1"),
                subprocess.CalledProcessError(1, ["docker", "compose"], "out2", "err2"),
                subprocess.CompletedProcess(
                    ["docker", "compose"], 0, stdout="", stderr=""
                ),
            ]
        )

        args = [
            "up",
            "-d",
            "--no-build",
            "coredns",
            "infinito",
        ]
        compose._compose_up_with_retries(args, attempts=6, delay_s=30)

        self.assertEqual(compose.run.call_count, 3)

        self.assertEqual(sleep_mock.call_count, 2)
        sleep_mock.assert_any_call(30)
        self.assertTrue(all(call.args == (30,) for call in sleep_mock.call_args_list))

    @patch("time.sleep", autospec=True)
    def test_compose_up_with_retries_raises_after_exhausting_attempts(
        self, sleep_mock: MagicMock
    ) -> None:
        compose = self._compose()

        compose.run = MagicMock(
            side_effect=subprocess.CalledProcessError(
                1, ["docker", "compose"], "out", "err"
            )
        )

        args = ["up", "-d", "coredns", "infinito"]

        with self.assertRaises(subprocess.CalledProcessError):
            compose._compose_up_with_retries(args, attempts=6, delay_s=30)

        self.assertEqual(compose.run.call_count, 6)

        self.assertEqual(sleep_mock.call_count, 5)
        self.assertTrue(all(call.args == (30,) for call in sleep_mock.call_args_list))

    @patch("time.sleep", autospec=True)
    def test_compose_up_with_retries_no_sleep_if_first_try_succeeds(
        self, sleep_mock: MagicMock
    ) -> None:
        compose = self._compose()

        compose.run = MagicMock(
            return_value=subprocess.CompletedProcess(
                ["docker", "compose"], 0, stdout="", stderr=""
            )
        )

        args = ["up", "-d", "coredns", "infinito"]
        compose._compose_up_with_retries(args, attempts=6, delay_s=30)

        self.assertEqual(compose.run.call_count, 1)
        sleep_mock.assert_not_called()

    @patch.dict(
        os.environ,
        {
            "INFINITO_IMAGE": "test-image/arch",
            "GITHUB_ACTIONS": "true",
            "INFINITO_RUNNING_ON_GITHUB": "true",
            "CI": "true",
            "INFINITO_GIT_COMMON_DIR": "",
            "INFINITO_CACHE_NETWORK": "",
            "INFINITO_CACHE_STACK": "",
            "INFINITO_GPU_COUNT": "0",
            "INFINITO_GHCR_MIRROR": "",
        },
        clear=False,
    )
    @patch(
        "cli.administration.deploy.development.runner_mirror.write_override",
        return_value="build/compose/runner-mirror.override.yml",
    )
    @patch("subprocess.run", autospec=True)
    def test_run_skips_cache_override_on_github_runner(
        self, run_mock: MagicMock, _write_override: MagicMock
    ) -> None:
        compose = self._compose()

        run_mock.return_value = subprocess.CompletedProcess(
            ["docker", "compose", "ps", "-q", "infinito"],
            0,
            stdout="cid\n",
            stderr="",
        )

        r = compose.run(["ps", "-q", "infinito"], check=False, capture=True)

        self.assertEqual(r.returncode, 0)
        self.assertEqual(run_mock.call_count, 1)

        cmd = run_mock.call_args.args[0]
        env = run_mock.call_args.kwargs["env"]

        self.assertEqual(
            cmd,
            [
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "-f",
                "compose/tools.override.yml",
                "-f",
                "build/compose/runner-mirror.override.yml",
                "ps",
                "-q",
                "infinito",
            ],
        )
        self.assertEqual(env["INFINITO_DISTRO"], "arch")
        self.assertNotIn("COMPOSE_PROFILES", env)

    @patch.dict(
        os.environ,
        {
            "INFINITO_IMAGE": "test-image/arch",
            "GITHUB_ACTIONS": "",
            "INFINITO_RUNNING_ON_GITHUB": "",
            "CI": "",
            "INFINITO_GIT_COMMON_DIR": "",
            "INFINITO_CACHE_NETWORK": "",
            "INFINITO_CACHE_STACK": "",
            "INFINITO_CACHE_SHARED_HOST_PATH": "",
            "INFINITO_CACHE_HOST_PACMAN_PATH": "",
            "INFINITO_GPU_COUNT": "0",
            "INFINITO_GHCR_MIRROR": "",
        },
        clear=False,
    )
    @patch("subprocess.run", autospec=True)
    def test_run_layers_cache_override_locally(self, run_mock: MagicMock) -> None:
        compose = self._compose()

        run_mock.return_value = subprocess.CompletedProcess(
            ["docker", "compose"], 0, stdout="", stderr=""
        )

        compose.run(["ps", "-q", "infinito"], check=False, capture=True)

        cmd = run_mock.call_args.args[0]
        env = run_mock.call_args.kwargs["env"]

        self.assertEqual(
            cmd,
            [
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "-f",
                "compose/cache.override.yml",
                "-f",
                "compose/tools.override.yml",
                "ps",
                "-q",
                "infinito",
            ],
        )
        self.assertEqual(
            env["INFINITO_CACHE_REGISTRY_PROXY_CONF"],  # nocheck: test-fixture
            "./compose/registry-cache/proxy.conf",
        )
        self.assertTrue(
            env["INFINITO_CACHE_PACKAGE_FRONTEND_CA_FILE"].endswith(
                "/ca.crt"
            )  # nocheck: test-fixture
        )

    @patch.dict(
        os.environ,
        {
            "INFINITO_BUILD": "1",
            "INFINITO_IMAGE": "infinito-debian",
            "INFINITO_PULL_POLICY": "never",
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "INFINITO_RUNNING_ON_GITHUB": "true",
            "INFINITO_CACHE_STACK": "",
            "INFINITO_GHCR_MIRROR": "",
        },
        clear=False,
    )
    def test_up_builds_when_build_flag_is_enabled(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()
        compose.reset_target = MagicMock()

        with patch.object(pin, "served_hosts", return_value=None):
            compose.up(run_entry_init=False)

        compose._compose_up_with_retries.assert_called_once_with(
            ["up", "-d", "coredns", "infinito"],
            attempts=6,
            delay_s=30,
        )
        compose.wait_for_healthy.assert_called_once_with()
        compose.reset_target.assert_called_once_with()

    @patch.dict(
        os.environ,
        {
            "INFINITO_BUILD": "0",
            "INFINITO_IMAGE": "test-image/arch",
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "INFINITO_RUNNING_ON_GITHUB": "true",
            "INFINITO_CACHE_STACK": "",
            "INFINITO_GHCR_MIRROR": "",
        },
        clear=False,
    )
    def test_up_skips_build_when_build_flag_is_disabled(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()
        compose.reset_target = MagicMock()

        with patch.object(pin, "served_hosts", return_value=None):
            compose.up(run_entry_init=False)

        compose._compose_up_with_retries.assert_called_once_with(
            [
                "up",
                "-d",
                "--no-build",
                "coredns",
                "infinito",
            ],
            attempts=6,
            delay_s=30,
        )
        compose.wait_for_healthy.assert_called_once_with()

    @patch.dict(
        os.environ,
        {
            "INFINITO_BUILD": "1",
            "INFINITO_IMAGE": "infinito-debian",
            "INFINITO_PULL_POLICY": "never",
            "CI": "",
            "GITHUB_ACTIONS": "",
            "INFINITO_RUNNING_ON_GITHUB": "",
            "INFINITO_GIT_COMMON_DIR": "",
            "INFINITO_CACHE_NETWORK": "",
            "INFINITO_CACHE_STACK": "",
            "INFINITO_CACHE_SHARED_HOST_PATH": "/var/cache/infinito/core/cache/shared",
            "INFINITO_GHCR_MIRROR": "",
        },
        clear=False,
    )
    def test_up_includes_cache_services_when_local(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()
        compose.reset_target = MagicMock()
        compose._apply_pinned_cache = MagicMock()
        compose._prepare_pinned_cache = MagicMock()
        compose._install_package_frontend_ca_in_runner = MagicMock()
        compose._layer_pacman_cache_in_runner = MagicMock()

        compose.up(run_entry_init=False)

        compose._compose_up_with_retries.assert_called_once_with(
            [
                "up",
                "-d",
                "registry-cache",
                "package-cache",
                "package-cache-frontend",
                "coredns",
                "infinito",
            ],
            attempts=6,
            delay_s=30,
        )
        compose.wait_for_healthy.assert_called_once_with()
        compose._apply_pinned_cache.assert_called_once()
        compose._prepare_pinned_cache.assert_called_once()
        compose._install_package_frontend_ca_in_runner.assert_called_once()
        compose._layer_pacman_cache_in_runner.assert_called_once()

    @patch.dict(
        os.environ,
        {
            "INFINITO_BUILD": "1",
            "INFINITO_IMAGE": "infinito-debian",
            "INFINITO_PULL_POLICY": "never",
            "CI": "",
            "GITHUB_ACTIONS": "",
            "INFINITO_RUNNING_ON_GITHUB": "",
            "INFINITO_GIT_COMMON_DIR": "/primary/.git",
            "INFINITO_CACHE_NETWORK": "infinito-nexus-core_default",
            "INFINITO_CACHE_STACK": "",
            "INFINITO_CACHE_SHARED_HOST_PATH": "/var/cache/infinito/core/cache/shared",
        },
        clear=False,
    )
    def test_up_applies_the_pinned_declarations_to_a_cache_stack_it_shares(
        self,
    ) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()
        compose.reset_target = MagicMock()
        compose._prepare_pinned_cache = MagicMock()
        compose._apply_pinned_cache = MagicMock()
        compose._install_package_frontend_ca_in_runner = MagicMock()
        compose._layer_pacman_cache_in_runner = MagicMock()

        compose.up(run_entry_init=False)

        compose._compose_up_with_retries.assert_called_once_with(
            ["up", "-d", "coredns", "infinito"], attempts=6, delay_s=30
        )
        compose._prepare_pinned_cache.assert_not_called()
        compose._apply_pinned_cache.assert_called_once()
        compose._install_package_frontend_ca_in_runner.assert_called_once()
        compose._layer_pacman_cache_in_runner.assert_called_once()

    @patch.dict(
        os.environ,
        {
            "INFINITO_BUILD": "1",
            "INFINITO_IMAGE": "infinito-debian",
            "INFINITO_PULL_POLICY": "never",
            "CI": "",
            "GITHUB_ACTIONS": "",
            "INFINITO_RUNNING_ON_GITHUB": "",
            "INFINITO_GIT_COMMON_DIR": "",
            "INFINITO_CACHE_NETWORK": "",
            "INFINITO_CACHE_STACK": "",
            "INFINITO_CACHE_SHARED_HOST_PATH": "",
            "INFINITO_GHCR_MIRROR": "",
        },
        clear=False,
    )
    def test_up_skips_the_pacman_layering_without_a_shared_folder(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()
        compose._apply_pinned_cache = MagicMock()
        compose._prepare_pinned_cache = MagicMock()
        compose._install_package_frontend_ca_in_runner = MagicMock()
        compose._layer_pacman_cache_in_runner = MagicMock()
        compose.reset_target = MagicMock()

        compose.up(run_entry_init=False)

        compose._install_package_frontend_ca_in_runner.assert_called_once()
        compose._layer_pacman_cache_in_runner.assert_not_called()

    @patch.dict(
        os.environ,
        {
            "INFINITO_CACHE_SHARED_HOST_PATH": "/var/cache/infinito/core/cache/shared",
            "INFINITO_CACHE_HOST_PACMAN_PATH": "/var/cache/pacman/pkg",
        },
        clear=False,
    )
    def test_the_runner_layers_pacman_over_both_caches(self) -> None:
        compose = self._compose()
        compose.exec = MagicMock()

        compose._layer_pacman_cache_in_runner()

        compose.exec.assert_called_once_with(
            [
                "/usr/local/bin/pacman-cache.sh",
                "/etc/pacman.conf",
                "/var/cache/infinito/core/cache/shared",
                "/var/cache/pacman/pkg",
            ],
            live=False,
        )

    @patch.dict(os.environ, {"INFINITO_GHCR_MIRROR": ""}, clear=False)
    def test_the_cache_stack_starts_and_applies_through_the_pinned_apply(
        self,
    ) -> None:
        compose = self._compose()
        helper = str(compose.repo_root / "scripts" / "system" / "cache" / "apply.sh")
        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            compose._prepare_pinned_cache({})
            compose._apply_pinned_cache({})
        prepare, apply = run.call_args_list
        self.assertEqual(prepare.args[0], ["bash", helper, "prepare"])
        self.assertEqual(apply.args[0], ["bash", helper])

    @patch.dict(os.environ, {"INFINITO_GHCR_MIRROR": ""}, clear=False)
    def test_no_pin_stops_the_owner_with_the_declarer_hint_but_never_a_sharer(
        self,
    ) -> None:
        compose = self._compose()
        with patch("subprocess.run") as run:
            run.return_value.returncode = 3
            with self.assertRaises(SystemExit) as stopped:
                compose._prepare_pinned_cache({})
            compose._apply_pinned_cache({})
        self.assertIn("make cache-declare ref=<commit>", str(stopped.exception.code))
        self.assertIn("make dotenv", str(stopped.exception.code))

    def test_the_hijacks_are_rendered_against_the_pinned_declarations(self) -> None:
        compose = self._compose()
        served = {"a.example": {"repo": "raw-a"}}
        module = "cli.administration.deploy.development.compose"
        with (
            patch(f"{module}.pin.served_hosts", return_value=served) as pinned,
            patch(f"{module}.render_artifacts", return_value=[]) as render,
        ):
            compose._render_cache_artifacts()
        pinned.assert_called_once_with(os.environ)
        self.assertIs(render.call_args.args[2], served)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
