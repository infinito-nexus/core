from __future__ import annotations

import dataclasses
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.infra import __main__ as cli
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.infra_inventory import (
    CACHE_ROLES,
    GATED_ROLES,
    INVENTORY_KEYS,
    INVENTORY_TEMPLATE,
    OPT_IN_ROLES,
    POOL_KEY,
    POOL_ROLE,
    REGISTRIES_KEY,
    SRC_KEY,
    Pool,
    infra_roles,
    opted_out,
    pool_refusal,
    render_inventory,
)
from utils.inventory.tools_idle import GRACE_KEY, STAMP_DIR_KEY

BASE = Path("/c/cache")
QUEUE = "/c/cache/jobs"
ROOTS = ("/home/operator/Repositories/core", "/home/operator/.local/share/worktrees")
SRC = ROOTS[0]
IMAGE = "infinito/arch:0123abcd"
OPERATOR = 1000
POOL = Pool(
    count=3,
    roots=ROOTS,
    queue=QUEUE,
    src=SRC,
    image=IMAGE,
    uid=OPERATOR,
    gid=OPERATOR,
)
PROVISION = "cli.administration.inventory.provision"
RUNTIME = {
    cli.VENV_KEY: "/opt/venvs/infinito",
    GRACE_KEY: "2h",
    STAMP_DIR_KEY: "/c/cache/tools",
}
RENDER_ENV = {
    **{key: f"/c/{name}" for name, key in INVENTORY_KEYS.items()},
    REGISTRIES_KEY: "ghcr.io quay.io",
}


def _render(pool: Pool | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        template = root / INVENTORY_TEMPLATE
        template.parent.mkdir(parents=True)
        template.write_text(
            read_text(str(PROJECT_ROOT / INVENTORY_TEMPLATE)), encoding="utf-8"
        )
        return load_yaml(render_inventory(root, RENDER_ENV, pool))


def _env(pool: str) -> dict[str, str]:
    kept = {k: v for k, v in os.environ.items() if k not in GATED_ROLES}
    return {
        **kept,
        **RUNTIME,
        POOL_KEY: pool,
        cli.ROOTS_KEY: "",
        SRC_KEY: SRC,
        cli.IMAGE_KEY: IMAGE,
    }


def _installs(pool: str, count: object) -> tuple[list[list[str]], list]:
    rendered: list = []

    def render(_root, _env_, pool_value):
        rendered.append(pool_value)
        return Path("/c/infra.rendered.yml")

    with (
        patch.dict(os.environ, _env(pool), clear=True),
        patch("os.getuid", return_value=OPERATOR),
        patch("os.getgid", return_value=OPERATOR),
        patch.object(cli, "render_inventory", side_effect=render),
        patch.object(cli, "_runner_count", side_effect=count),
        patch.object(cli, "base", return_value=BASE),
        patch.object(cli, "queue_root", return_value=Path(QUEUE)),
        patch.object(cli, "idle_units", return_value={}),
        patch.object(cli, "write_units"),
        patch.object(cli, "timer_installs", return_value=[]),
    ):
        return cli._installs(["compose"], Path(ROOTS[0])), rendered


def _included(commands: list[list[str]]) -> list[str]:
    provision = next(command for command in commands if PROVISION in command)
    return provision[provision.index("--include") + 1 : provision.index("--vars-file")]


class TestThePoolGate(unittest.TestCase):
    def test_the_flag_adds_only_the_runner_role(self) -> None:
        self.assertEqual(infra_roles({POOL_KEY: "true"}), (*CACHE_ROLES, POOL_ROLE))
        self.assertEqual(infra_roles({POOL_KEY: "false"}), CACHE_ROLES)
        self.assertEqual(infra_roles({}), CACHE_ROLES)

    def test_without_the_flag_the_runner_role_leaves_the_inventory(self) -> None:
        self.assertIn(POOL_ROLE, opted_out({}))
        self.assertNotIn(POOL_ROLE, opted_out({POOL_KEY: "true"}))

    def test_a_value_other_than_true_or_false_is_refused(self) -> None:
        with self.assertRaises(ValueError) as raised:
            infra_roles({POOL_KEY: "yes"})
        self.assertIn(POOL_KEY, str(raised.exception))

    def test_the_pool_is_no_phase_nine_opt_in(self) -> None:
        self.assertNotIn(POOL_KEY, OPT_IN_ROLES)
        self.assertEqual(GATED_ROLES, {**OPT_IN_ROLES, POOL_KEY: POOL_ROLE})


class TestThePoolInTheInventory(unittest.TestCase):
    def test_the_inventory_declares_n_local_runners_on_the_queue_and_roots(
        self,
    ) -> None:
        rendered = _render(POOL)
        self.assertEqual(rendered["RUNNER_COUNT"], 3)
        self.assertEqual(
            rendered["applications"][POOL_ROLE]["services"]["runner"],
            {
                "flavor": "local",
                "queue_dir": QUEUE,
                "src_dir": SRC,
                "toolchain_image": IMAGE,
                "operator_uid": OPERATOR,
                "operator_gid": OPERATOR,
                "worktree_roots": list(ROOTS),
            },
        )

    def test_without_a_pool_the_inventory_holds_no_runner(self) -> None:
        rendered = _render(None)
        self.assertNotIn("RUNNER_COUNT", rendered)
        self.assertNotIn(POOL_ROLE, rendered["applications"])

    def test_the_pool_changes_nothing_else(self) -> None:
        with_pool, without = _render(POOL), _render(None)
        del with_pool["RUNNER_COUNT"]
        del with_pool["applications"][POOL_ROLE]
        self.assertEqual(with_pool, without)


class TestThePoolRefusals(unittest.TestCase):
    def test_a_usable_pool_passes(self) -> None:
        self.assertEqual(pool_refusal(POOL, BASE), [])

    def test_each_unusable_value_is_named(self) -> None:
        for changed, word in (
            ({"count": 0}, "at least 1 runner"),
            ({"roots": (), "src": ""}, "no worktree root"),
            ({"queue": "/var/cache/jobs"}, "/var/cache/jobs"),
            ({"src": ""}, SRC_KEY),
            ({"src": "/opt/elsewhere"}, SRC_KEY),
            ({"image": ""}, "toolchain image"),
            ({"uid": 0}, "never runs as root"),
            ({"gid": 0}, "never runs as root"),
        ):
            with self.subTest(word=word, changed=changed):
                refusals = pool_refusal(dataclasses.replace(POOL, **changed), BASE)
                self.assertEqual(len(refusals), 1 + ("roots" in changed), refusals)
                self.assertIn(word, refusals[0])


class TestTheInfraDeploy(unittest.TestCase):
    def test_with_the_flag_the_deploy_includes_the_sized_pool(self) -> None:
        commands, rendered = _installs("true", [2])
        self.assertEqual(_included(commands), [*CACHE_ROLES, POOL_ROLE])
        worktrees = str(Path.home() / ".local" / "share" / "worktrees")
        self.assertEqual(
            rendered,
            [dataclasses.replace(POOL, count=2, roots=(ROOTS[0], worktrees))],
        )
        self.assertEqual(commands[0], cli.image_load(["compose"], IMAGE))

    def test_the_toolchain_image_reaches_the_inner_daemon_unless_it_holds_it(
        self,
    ) -> None:
        command = cli.image_load(["compose"], IMAGE)
        self.assertEqual(command[:2], ["bash", "-c"])
        self.assertEqual(command[3:5], ["image-load", IMAGE])
        self.assertEqual(command[5:], cli.inner_docker(["compose"], []))
        self.assertIn("image inspect", command[2])
        self.assertIn('docker save "$image" | "$@" load', command[2])

    def test_without_the_flag_nothing_is_sized_and_no_runner_deploys(self) -> None:
        commands, rendered = _installs("false", AssertionError("sized"))
        self.assertEqual(_included(commands), list(CACHE_ROLES))
        self.assertEqual(rendered, [None])
        self.assertNotIn(cli.image_load(["compose"], IMAGE), commands)

    def test_an_unsized_pool_refuses_before_the_inventory_renders(self) -> None:
        refusal = subprocess.CompletedProcess(
            [], 2, stdout="", stderr="[runner-count] calibration does not exist"
        )
        with (
            patch.dict(os.environ, _env("true"), clear=True),
            patch.object(cli.subprocess, "run", return_value=refusal),
            patch.object(cli, "render_inventory", side_effect=AssertionError),
            self.assertRaises(SystemExit) as raised,
        ):
            cli._installs(["compose"], Path(ROOTS[0]))
        self.assertIn(POOL_KEY, str(raised.exception))
        self.assertIn("calibration does not exist", str(raised.exception))

    def test_a_queue_the_infra_runner_does_not_see_refuses_before_the_render(
        self,
    ) -> None:
        with (
            patch.dict(os.environ, _env("true"), clear=True),
            patch.object(cli, "_runner_count", return_value=2),
            patch.object(cli, "base", return_value=BASE),
            patch.object(cli, "queue_root", return_value=Path("/var/cache/jobs")),
            patch.object(cli, "render_inventory", side_effect=AssertionError),
            self.assertRaises(SystemExit) as raised,
        ):
            cli._installs(["compose"], Path(ROOTS[0]))
        self.assertIn("/var/cache/jobs", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
