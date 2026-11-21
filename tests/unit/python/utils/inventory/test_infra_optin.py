from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.infra import __main__ as cli
from utils import PROJECT_ROOT
from utils.cache.yaml import dump_yaml, load_yaml
from utils.env.parser import parse_static_env
from utils.infra_inventory import (
    CACHE_ROLES,
    OPT_IN_ROLES,
    PRUNE_ACTION,
    infra_roles,
    opted_out,
)
from utils.inventory.tools_idle import GRACE_KEY, STAMP_DIR_KEY

SEMAPHORE_KEY = "INFINITO_INFRA_SEMAPHORE"
CHECKMK_KEY = "INFINITO_INFRA_CHECKMK"
SEMAPHORE = "web-app-semaphore"
CHECKMK = "web-app-checkmk"
OPTIONAL = (SEMAPHORE, CHECKMK)
PROVISION = "cli.administration.inventory.provision"
DEPLOY = "cli.administration.deploy.dedicated"
RUNTIME = {
    cli.VENV_KEY: "/opt/venvs/infinito",
    GRACE_KEY: "2h",
    STAMP_DIR_KEY: "/var/cache/infinito/core/cache/tools",
}


def _env(env: dict[str, str]) -> dict[str, str]:
    stripped = {
        key: value for key, value in os.environ.items() if key not in OPT_IN_ROLES
    }
    return {**stripped, **RUNTIME, **env}


def _commands(env: dict[str, str]) -> list[list[str]]:
    with (
        patch.dict(os.environ, _env(env), clear=True),
        patch.object(
            cli, "render_inventory", return_value=Path("/c/infra.rendered.yml")
        ),
        patch.object(cli, "base", return_value=Path("/c/cache")),
        patch.object(cli, "idle_units", return_value={}),
        patch.object(cli, "write_units"),
        patch.object(cli, "timer_installs", return_value=[]),
    ):
        return cli._installs(["compose"], Path("/c"))


def _position(commands: list[list[str]], module: str) -> int:
    return next(index for index, c in enumerate(commands) if module in c)


def _included(env: dict[str, str]) -> list[str]:
    commands = _commands(env)
    provision = commands[_position(commands, PROVISION)]
    start = provision.index("--include") + 1
    return provision[start : provision.index("--vars-file")]


def _pruned(env: dict[str, str]) -> list[str]:
    commands = _commands(env)
    prune = commands[_position(commands, PRUNE_ACTION)]
    return prune[prune.index(PRUNE_ACTION) + 2 :]


def _inventory(path: Path, roles: tuple[str, ...]) -> None:
    hosts = {"hosts": {"localhost": {}}}
    dump_yaml(path, {"all": {"children": {role: dict(hosts) for role in roles}}})


class TestOptInDefaults(unittest.TestCase):
    def test_default_env_declares_both_opt_ins_off(self) -> None:
        declared = parse_static_env(PROJECT_ROOT / "default.env")
        self.assertEqual(
            {key: declared.get(key) for key in (SEMAPHORE_KEY, CHECKMK_KEY)},
            {SEMAPHORE_KEY: "false", CHECKMK_KEY: "false"},
        )

    def test_the_opt_ins_name_exactly_the_two_optional_roles(self) -> None:
        self.assertEqual(OPT_IN_ROLES, {SEMAPHORE_KEY: SEMAPHORE, CHECKMK_KEY: CHECKMK})


class TestInfraRoles(unittest.TestCase):
    def test_unset_opt_ins_hold_only_the_cache_roles(self) -> None:
        self.assertEqual(infra_roles({}), CACHE_ROLES)

    def test_false_opt_ins_hold_only_the_cache_roles(self) -> None:
        env = {SEMAPHORE_KEY: "false", CHECKMK_KEY: "false"}
        self.assertEqual(infra_roles(env), CACHE_ROLES)

    def test_each_opt_in_adds_only_its_own_role(self) -> None:
        self.assertEqual(
            infra_roles({SEMAPHORE_KEY: "true"}), (*CACHE_ROLES, SEMAPHORE)
        )
        self.assertEqual(infra_roles({CHECKMK_KEY: "true"}), (*CACHE_ROLES, CHECKMK))
        both = {SEMAPHORE_KEY: "true", CHECKMK_KEY: "true"}
        self.assertEqual(infra_roles(both), (*CACHE_ROLES, SEMAPHORE, CHECKMK))

    def test_a_value_other_than_true_or_false_is_refused(self) -> None:
        with self.assertRaises(ValueError) as raised:
            infra_roles({SEMAPHORE_KEY: "yes"})
        self.assertIn(SEMAPHORE_KEY, str(raised.exception))


class TestTheInfraDeployIncludes(unittest.TestCase):
    def test_without_the_opt_ins_neither_role_is_deployed(self) -> None:
        included = _included({})
        self.assertEqual(included, list(CACHE_ROLES))
        self.assertFalse(set(OPTIONAL) & set(included))

    def test_with_both_opt_ins_off_neither_role_is_deployed(self) -> None:
        included = _included({SEMAPHORE_KEY: "false", CHECKMK_KEY: "false"})
        self.assertFalse(set(OPTIONAL) & set(included))

    def test_each_opt_in_reaches_the_deploy(self) -> None:
        self.assertEqual(_included({SEMAPHORE_KEY: "true"}), [*CACHE_ROLES, SEMAPHORE])
        self.assertEqual(_included({CHECKMK_KEY: "true"}), [*CACHE_ROLES, CHECKMK])


class TestAnOptOutLeavesTheInventory(unittest.TestCase):
    def test_the_prune_runs_between_the_provision_and_the_deploy(self) -> None:
        commands = _commands({})
        self.assertLess(
            _position(commands, PROVISION), _position(commands, PRUNE_ACTION)
        )
        self.assertLess(_position(commands, PRUNE_ACTION), _position(commands, DEPLOY))

    def test_the_prune_names_every_opted_out_role_only(self) -> None:
        self.assertEqual(_pruned({}), list(OPTIONAL))
        self.assertEqual(_pruned({SEMAPHORE_KEY: "true"}), [CHECKMK])

    def test_a_role_an_earlier_opt_in_provisioned_leaves_the_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            devices = Path(tmp) / "devices.yml"
            _inventory(devices, (*CACHE_ROLES, *OPTIONAL))
            with patch("sys.stderr", io.StringIO()):
                code = cli.main([PRUNE_ACTION, str(devices), *opted_out({})])
            children = load_yaml(devices)["all"]["children"]
        self.assertEqual(code, 0)
        self.assertEqual(sorted(children), sorted(CACHE_ROLES))

    def test_a_kept_opt_in_stays_in_the_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            devices = Path(tmp) / "devices.yml"
            _inventory(devices, (*CACHE_ROLES, *OPTIONAL))
            with patch("sys.stderr", io.StringIO()):
                cli.main(
                    [PRUNE_ACTION, str(devices), *opted_out({SEMAPHORE_KEY: "true"})]
                )
            children = load_yaml(devices)["all"]["children"]
        self.assertEqual(sorted(children), sorted((*CACHE_ROLES, SEMAPHORE)))


class TestABadOptInStartsNothing(unittest.TestCase):
    def test_up_refuses_before_the_runner_is_prepared(self) -> None:
        for action in ("up", "update", "attach"):
            with (
                self.subTest(action=action),
                patch.dict(
                    os.environ,
                    _env({SEMAPHORE_KEY: "yes", "INFINITO_CACHE_STACK": "true"}),
                    clear=True,
                ),
                patch.object(cli, "_prepare") as prepare,
                patch.object(cli, "up") as start,
                self.assertRaises(SystemExit) as raised,
            ):
                cli.main([action])
            self.assertIn(SEMAPHORE_KEY, str(raised.exception))
            prepare.assert_not_called()
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
