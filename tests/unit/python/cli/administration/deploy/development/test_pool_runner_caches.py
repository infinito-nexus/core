from __future__ import annotations

import io
import os
import unittest
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.compose import Compose
from cli.administration.deploy.development.env import (
    INFRA_CONSUMER,
    POOL_CONSUMER,
    compose_file_args,
)
from cli.administration.infra import __main__ as infra_cli
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.render import cache_consumer_yml
from utils.cache.yaml import load_yaml, load_yaml_str
from utils.env.handlers.infinito import infra as infra_handler
from utils.networks.infra import SUBNET_KEY, runner_ip
from utils.runner import POOL_RUNNER_KEY

HOST = {
    "INFINITO_BUILD": "0",
    "INFINITO_IMAGE": "infinito-arch",
    "INFINITO_OUTER_NETWORK_MTU": "1500",
    "CI": "",
    "GITHUB_ACTIONS": "",
    "INFINITO_RUNNING_ON_GITHUB": "",
    "INFINITO_GIT_COMMON_DIR": "",
    "INFINITO_CACHE_STACK": "",
    "INFINITO_CACHE_SHARED_HOST_PATH": "",
    "INFINITO_CACHE_HOST_PACMAN_PATH": "",
    "INFINITO_GHCR_MIRROR": "",
    "INFINITO_PUBLISH_PORTS": "",
    "INFINITO_GPU_COUNT": "0",
    "INFINITO_EXTRA_MOUNTS": "",
    POOL_RUNNER_KEY: "",
}
POOL_JOB = {**HOST, POOL_RUNNER_KEY: "true"}


class _Builder:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = dict(values)

    def get(self, key: str) -> str:
        return self.values.get(key, "")

    def set(self, key: str, value: str, comment: str) -> None:
        self.values[key] = value

    def setdefault(self, key: str, value: str, comment: str) -> None:
        self.values.setdefault(key, value)


def _up(env: dict[str, str]) -> Compose:
    with patch.dict(os.environ, env, clear=False):
        compose = Compose(repo_root=PROJECT_ROOT, distro="arch")
        compose._render_cache_artifacts = MagicMock()
        compose._render_coredns_corefile = MagicMock()
        compose._prepare_vulnerability_db = MagicMock()
        compose._ensure_infra = MagicMock()
        compose._compose_up_with_retries = MagicMock()
        compose.wait_for_healthy = MagicMock()
        compose._install_package_frontend_ca_in_runner = MagicMock()
        compose.up(run_entry_init=False)
    return compose


def _files(env: dict[str, str]) -> list[str]:
    with patch.dict(os.environ, env, clear=False):
        return compose_file_args()


class TestAPoolJobTakesTheCachesButNoInfraOfItsOwn(unittest.TestCase):
    def test_a_pool_job_renders_the_caches_and_never_starts_or_joins_infra(
        self,
    ) -> None:
        compose = _up(POOL_JOB)
        files = _files(POOL_JOB)
        compose._ensure_infra.assert_not_called()
        compose._install_package_frontend_ca_in_runner.assert_called_once()
        self.assertEqual(
            [POOL_CONSUMER in files, INFRA_CONSUMER in files], [True, False]
        )

    def test_without_the_pool_runner_the_host_path_starts_and_joins_infra(
        self,
    ) -> None:
        compose = _up(HOST)
        files = _files(HOST)
        compose._ensure_infra.assert_called_once()
        compose._install_package_frontend_ca_in_runner.assert_called_once()
        self.assertEqual(
            [POOL_CONSUMER in files, INFRA_CONSUMER in files], [False, True]
        )

    def test_a_disabled_cache_stack_still_wins_over_the_pool_runner(self) -> None:
        env = {**POOL_JOB, "INFINITO_CACHE_STACK": "false"}
        self.assertEqual(
            [POOL_CONSUMER in _files(env), INFRA_CONSUMER in _files(env)],
            [False, False],
        )

    def test_the_pool_override_keeps_the_cache_consumer_and_drops_the_network(
        self,
    ) -> None:
        pool = load_yaml(PROJECT_ROOT / POOL_CONSUMER)
        host = load_yaml(PROJECT_ROOT / INFRA_CONSUMER)
        self.assertEqual(
            pool["services"]["infinito"]["extends"],
            host["services"]["infinito"]["extends"],
        )
        self.assertEqual(
            [
                "networks" in pool,
                "networks" in pool["services"]["infinito"],
                host["networks"]["infra"]["name"],
            ],
            [False, False, "infinito-infra"],
        )


class TestTheJobReachesTheInfraRunnerAtItsOwnAddress(unittest.TestCase):
    def test_every_cache_address_is_the_infra_runners_address_of_the_subnet(
        self,
    ) -> None:
        for subnet in ("10.47.0.0/24", "10.99.3.0/24"):
            builder = _Builder({SUBNET_KEY: subnet})
            infra_handler.apply(builder, None)
            with self.subTest(subnet=subnet):
                self.assertEqual(
                    {
                        key: builder.values[key]
                        for key in (
                            infra_handler.RUNNER_IP_KEY,
                            *infra_handler.CACHE_IP_KEYS,
                        )
                    },
                    dict.fromkeys(
                        (infra_handler.RUNNER_IP_KEY, *infra_handler.CACHE_IP_KEYS),
                        runner_ip(subnet),
                    ),
                )

    def test_the_job_maps_the_cache_hosts_and_the_runner_binds_the_same_key(
        self,
    ) -> None:
        consumer = load_yaml_str(cache_consumer_yml())["services"]["cache-consumer"]
        self.assertIn("${INFINITO_CACHE_REGISTRY_IP:?", consumer["extra_hosts"][0])
        self.assertTrue(
            consumer["extra_hosts"][0].startswith("infinito-registry-cache:")
        )
        self.assertIn(
            "ipv4_address: ${INFINITO_INFRA_RUNNER_IP:?",
            read_text(str(PROJECT_ROOT / "compose" / "infra.yml")),
        )

    def test_without_a_subnet_no_cache_address_is_made_up(self) -> None:
        builder = _Builder({})
        infra_handler.apply(builder, None)
        self.assertEqual(builder.values, {})


class TestTheInfraCliRefusesAPoolJob(unittest.TestCase):
    def _main(self, action: str, env: dict[str, str]) -> str:
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(
                infra_cli, "infra_roles", side_effect=ValueError("past the gate")
            ),
            patch("sys.stderr", io.StringIO()),
            self.assertRaises(SystemExit) as stopped,
        ):
            infra_cli.main([action])
        return str(stopped.exception.code)

    def test_a_pool_job_never_starts_updates_or_attaches_the_infra_runner(
        self,
    ) -> None:
        for action in infra_cli.STARTING:
            with self.subTest(action=action):
                self.assertIn(POOL_RUNNER_KEY, self._main(action, POOL_JOB))

    def test_the_host_passes_the_gate_for_every_starting_action(self) -> None:
        for action in infra_cli.STARTING:
            with self.subTest(action=action):
                self.assertEqual(self._main(action, HOST), "past the gate")


if __name__ == "__main__":
    unittest.main()
