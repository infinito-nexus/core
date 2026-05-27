# tests/cli/administration/deploy/development/test_compose.py
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.compose import Compose


class TestComposeUpRetries(unittest.TestCase):
    def _compose(self) -> Compose:
        # repo_root is only used as a cwd in subprocess calls; for these unit tests
        # we do not execute real subprocesses.
        return Compose(repo_root=Path("/tmp/infinito-nexus"), distro="arch")

    @patch("time.sleep", autospec=True)
    def test_compose_up_with_retries_succeeds_after_transient_failures(
        self, sleep_mock: MagicMock
    ) -> None:
        compose = self._compose()

        # Fail 2 times, then succeed.
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

        # 3 calls: fail, fail, succeed
        self.assertEqual(compose.run.call_count, 3)

        # Sleep after each failure (2 times), not after success
        self.assertEqual(sleep_mock.call_count, 2)
        sleep_mock.assert_any_call(30)
        # Ensure all sleeps used exactly 30 seconds
        self.assertTrue(all(call.args == (30,) for call in sleep_mock.call_args_list))

    @patch("time.sleep", autospec=True)
    def test_compose_up_with_retries_raises_after_exhausting_attempts(
        self, sleep_mock: MagicMock
    ) -> None:
        compose = self._compose()

        # Always fail.
        compose.run = MagicMock(
            side_effect=subprocess.CalledProcessError(
                1, ["docker", "compose"], "out", "err"
            )
        )

        args = ["up", "-d", "coredns", "infinito"]

        with self.assertRaises(subprocess.CalledProcessError):
            compose._compose_up_with_retries(args, attempts=6, delay_s=30)

        # Called exactly 6 times
        self.assertEqual(compose.run.call_count, 6)

        # Sleep between attempts: after attempts 1..5 => 5 sleeps
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
        },
        clear=False,
    )
    @patch("subprocess.run", autospec=True)
    def test_run_skips_cache_override_on_github_runner(
        self, run_mock: MagicMock
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

        # CI: cache override is not layered in.
        self.assertEqual(
            cmd,
            [
                "docker",
                "compose",
                "-f",
                "compose.yml",
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

        # Local: cache override is layered onto compose.yml.
        self.assertEqual(
            cmd,
            [
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "-f",
                "compose/cache.override.yml",
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
            # CI-pinned so cache stays inactive; this test asserts build behaviour only.
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "INFINITO_RUNNING_ON_GITHUB": "true",
        },
        clear=False,
    )
    def test_up_builds_when_build_flag_is_enabled(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()

        compose.up(run_entry_init=False)

        compose._compose_up_with_retries.assert_called_once_with(
            ["up", "-d", "coredns", "infinito"],
            attempts=6,
            delay_s=30,
        )
        compose.wait_for_healthy.assert_called_once_with()

    @patch.dict(
        os.environ,
        {
            "INFINITO_BUILD": "0",
            "INFINITO_IMAGE": "test-image/arch",
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "INFINITO_RUNNING_ON_GITHUB": "true",
        },
        clear=False,
    )
    def test_up_skips_build_when_build_flag_is_disabled(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()

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
        },
        clear=False,
    )
    def test_up_includes_cache_services_when_local(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()
        compose._bootstrap_package_cache = MagicMock()
        compose._generate_package_frontend_certs = MagicMock()
        compose._install_package_frontend_ca_in_runner = MagicMock()

        compose.up(run_entry_init=False)

        # Cache services precede coredns + infinito so depends_on health gates resolve.
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
        compose._bootstrap_package_cache.assert_called_once()
        compose._generate_package_frontend_certs.assert_called_once()
        compose._install_package_frontend_ca_in_runner.assert_called_once()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
