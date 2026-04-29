# tests/cli/deploy/development/test_compose.py
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.deploy.development.compose import Compose


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

        args = ["--env-file", "env.ci", "up", "-d", "--no-build", "coredns", "infinito"]
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

        args = ["--env-file", "env.ci", "up", "-d", "coredns", "infinito"]

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

        args = ["--env-file", "env.ci", "up", "-d", "coredns", "infinito"]
        compose._compose_up_with_retries(args, attempts=6, delay_s=30)

        self.assertEqual(compose.run.call_count, 1)
        sleep_mock.assert_not_called()

    @patch.dict(
        os.environ,
        {
            "INFINITO_IMAGE": "test-image/arch",
            "GITHUB_ACTIONS": "true",
            "RUNNING_ON_GITHUB": "true",
            "CI": "true",
        },
        clear=False,
    )
    @patch("subprocess.run", autospec=True)
    def test_run_uses_only_ci_profile_on_github_runner(
        self, run_mock: MagicMock
    ) -> None:
        compose = self._compose()

        run_mock.return_value = subprocess.CompletedProcess(
            ["docker", "compose", "--profile", "ci", "ps", "-q", "infinito"],
            0,
            stdout="cid\n",
            stderr="",
        )

        r = compose.run(["ps", "-q", "infinito"], check=False, capture=True)

        self.assertEqual(r.returncode, 0)
        self.assertEqual(run_mock.call_count, 1)

        cmd = run_mock.call_args.args[0]
        env = run_mock.call_args.kwargs["env"]

        # On GitHub-hosted runners the registry-cache stays inactive:
        # fresh disk per job means no cross-run amortization, so the
        # proxy adds startup latency without a payoff. Only the `ci`
        # profile fires.
        self.assertEqual(
            cmd,
            ["docker", "compose", "--profile", "ci", "ps", "-q", "infinito"],
        )
        self.assertEqual(env["INFINITO_DISTRO"], "arch")
        self.assertNotIn("COMPOSE_PROFILES", env)
        # And the proxy.conf bind-mount stays at /dev/null (the default
        # baked into compose.yml), so dockerd does direct pulls.
        self.assertNotIn("INFINITO_REGISTRY_CACHE_PROXY_CONF", env)

    @patch.dict(
        os.environ,
        {
            "INFINITO_IMAGE": "test-image/arch",
            "GITHUB_ACTIONS": "",
            "RUNNING_ON_GITHUB": "",
            "CI": "",
        },
        clear=False,
    )
    @patch("subprocess.run", autospec=True)
    def test_run_activates_cache_profile_locally(self, run_mock: MagicMock) -> None:
        compose = self._compose()

        run_mock.return_value = subprocess.CompletedProcess(
            ["docker", "compose"], 0, stdout="", stderr=""
        )

        compose.run(["ps", "-q", "infinito"], check=False, capture=True)

        cmd = run_mock.call_args.args[0]
        env = run_mock.call_args.kwargs["env"]

        # On a developer machine the cache profile activates so the
        # registry-cache joins the stack and infinito's depends_on
        # gates it via service_healthy.
        self.assertEqual(
            cmd,
            [
                "docker",
                "compose",
                "--profile",
                "ci",
                "--profile",
                "cache",
                "ps",
                "-q",
                "infinito",
            ],
        )
        # And the proxy.conf bind-mount points at the real file so
        # dockerd loads the systemd drop-in and routes pulls.
        self.assertEqual(
            env["INFINITO_REGISTRY_CACHE_PROXY_CONF"],
            "./compose/registry-cache/proxy.conf",
        )

    @patch.dict(
        os.environ,
        {
            "INFINITO_NO_BUILD": "0",
            "INFINITO_IMAGE": "infinito-debian",
            "INFINITO_PULL_POLICY": "never",
            # Pin to CI mode so the cache profile stays inactive: this
            # test asserts build behaviour, not the cache-services
            # ordering, which has its own coverage above.
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "RUNNING_ON_GITHUB": "true",
        },
        clear=False,
    )
    def test_up_builds_when_no_build_flag_is_disabled(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()

        compose.up(run_entry_init=False)

        compose._compose_up_with_retries.assert_called_once_with(
            ["--env-file", "env.ci", "up", "-d", "coredns", "infinito"],
            attempts=6,
            delay_s=30,
        )
        compose.wait_for_healthy.assert_called_once_with()

    @patch.dict(
        os.environ,
        {
            "INFINITO_NO_BUILD": "1",
            "INFINITO_IMAGE": "test-image/arch",
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "RUNNING_ON_GITHUB": "true",
        },
        clear=False,
    )
    def test_up_skips_build_when_no_build_flag_is_enabled(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()

        compose.up(run_entry_init=False)

        compose._compose_up_with_retries.assert_called_once_with(
            ["--env-file", "env.ci", "up", "-d", "--no-build", "coredns", "infinito"],
            attempts=6,
            delay_s=30,
        )
        compose.wait_for_healthy.assert_called_once_with()

    @patch.dict(
        os.environ,
        {
            "INFINITO_NO_BUILD": "0",
            "INFINITO_IMAGE": "infinito-debian",
            "INFINITO_PULL_POLICY": "never",
            "CI": "",
            "GITHUB_ACTIONS": "",
            "RUNNING_ON_GITHUB": "",
        },
        clear=False,
    )
    def test_up_includes_cache_services_when_local(self) -> None:
        compose = self._compose()
        compose._render_coredns_corefile = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()
        compose._bootstrap_package_cache = MagicMock()

        compose.up(run_entry_init=False)

        # Local mode -> cache profile active, registry-cache and
        # package-cache must precede coredns + infinito so they boot
        # first and the depends_on health gate resolves.
        compose._compose_up_with_retries.assert_called_once_with(
            [
                "--env-file",
                "env.ci",
                "up",
                "-d",
                "registry-cache",
                "package-cache",
                "coredns",
                "infinito",
            ],
            attempts=6,
            delay_s=30,
        )
        compose.wait_for_healthy.assert_called_once_with()
        compose._bootstrap_package_cache.assert_called_once()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
