from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.infra_inventory import (
    CHECKMK_OPT_IN,
    INVENTORY_KEYS,
    INVENTORY_TEMPLATE,
    OPT_IN_ROLES,
    REGISTRIES_KEY,
    SEMAPHORE_OPT_IN,
    Pool,
    render_inventory,
)

SEMAPHORE = OPT_IN_ROLES[SEMAPHORE_OPT_IN]
CHECKMK = OPT_IN_ROLES[CHECKMK_OPT_IN]
SRC = "/home/operator/.local/share/worktrees/github.com/infinito-nexus/core/main"
POOL = Pool(
    count=3,
    roots=("/home/operator/.local/share/worktrees",),
    queue="/c/cache/jobs",
    src=SRC,
    image="infinito/arch:0123abcd",
    uid=1000,
    gid=1000,
)
RENDER_ENV = {
    **{key: f"/c/{name}" for name, key in INVENTORY_KEYS.items()},
    REGISTRIES_KEY: "ghcr.io quay.io",
}
BASE_PATH = "utils.env.handlers.infinito.cache.paths.base"
BASE = Path("/c/cache")


def _render(opt_ins: dict[str, str], pool: Pool | None) -> tuple[dict, int]:
    with (
        tempfile.TemporaryDirectory() as tmp,
        patch(BASE_PATH, return_value=BASE) as cache_base,
    ):
        root = Path(tmp)
        template = root / INVENTORY_TEMPLATE
        template.parent.mkdir(parents=True)
        template.write_text(
            read_text(str(PROJECT_ROOT / INVENTORY_TEMPLATE)), encoding="utf-8"
        )
        rendered = render_inventory(root, {**RENDER_ENV, **opt_ins}, pool)
        return load_yaml(rendered)["applications"], cache_base.call_count


def _applications(opt_ins: dict[str, str], pool: Pool | None) -> dict:
    return _render(opt_ins, pool)[0]


class TestTheSemaphoreOptIn(unittest.TestCase):
    def test_with_the_pool_semaphore_seeds_one_runner_per_pool_runner(self) -> None:
        applications = _applications({SEMAPHORE_OPT_IN: "true"}, POOL)
        self.assertEqual(
            applications[SEMAPHORE]["services"]["semaphore"]["pool"],
            {"runners": POOL.count, "checkout": SRC},
        )

    def test_negative_control_without_the_opt_in_nothing_is_seeded(self) -> None:
        for opt_ins in ({}, {SEMAPHORE_OPT_IN: "false"}, {CHECKMK_OPT_IN: "true"}):
            with self.subTest(opt_ins=opt_ins):
                self.assertNotIn(SEMAPHORE, _applications(opt_ins, POOL))

    def test_negative_control_without_the_pool_nothing_is_seeded(self) -> None:
        self.assertNotIn(SEMAPHORE, _applications({SEMAPHORE_OPT_IN: "true"}, None))

    def test_a_bad_opt_in_is_refused_before_anything_is_written(self) -> None:
        with self.assertRaises(ValueError):
            _applications({SEMAPHORE_OPT_IN: "yes"}, POOL)


class TestTheCheckmkOptIn(unittest.TestCase):
    def test_checkmk_mounts_the_check_dir_below_the_cache_base(self) -> None:
        for pool in (POOL, None):
            with self.subTest(pool=pool):
                applications = _applications({CHECKMK_OPT_IN: "true"}, pool)
                self.assertEqual(
                    applications[CHECKMK]["services"]["checkmk"],
                    {"local_check_dir": "/c/cache/checkmk"},
                )

    def test_negative_control_without_the_opt_in_nothing_is_mounted(self) -> None:
        for opt_ins in ({}, {CHECKMK_OPT_IN: "false"}, {SEMAPHORE_OPT_IN: "true"}):
            with self.subTest(opt_ins=opt_ins):
                applications, base_calls = _render(opt_ins, POOL)
                self.assertNotIn(CHECKMK, applications)
                self.assertEqual(base_calls, 0)

    def test_a_bad_opt_in_is_refused_before_anything_is_written(self) -> None:
        with self.assertRaises(ValueError):
            _applications({CHECKMK_OPT_IN: "1"}, POOL)


if __name__ == "__main__":
    unittest.main()
