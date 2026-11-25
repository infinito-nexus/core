from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.evict import CACHES, FLOOR_KEY, IDLE_KEY
from utils.infra_checkmk import (
    CHECK_FILE,
    REQUIRED_KEYS,
    TIMER,
    check_dir,
    check_environment,
    check_setup,
    check_units,
)
from utils.infra_tools import idle_units
from utils.runner.checkmk_local_check import CRIT_KEY, WARN_KEY

PYTHON = "/opt/venvs/infinito/bin/python"
CHECKOUT = Path("/srv/core")
BASE = Path("/c/cache")
SHARED_PATH = "INFINITO_CACHE_SHARED_HOST_PATH"
ENV = {
    **{spec.cap_key: "1g" for spec in CACHES},
    IDLE_KEY: "7",
    FLOOR_KEY: "20g",
    WARN_KEY: "24h",
    CRIT_KEY: "7d",
    SHARED_PATH: "/c/cache/shared",
    "INFINITO_CACHE_PACKAGE_HOST_PATH": "",
    "HOME": "/home/operator",
}


class TestTheCheckEnvironment(unittest.TestCase):
    def test_it_carries_every_cap_the_floor_the_thresholds_and_set_paths(self) -> None:
        environment = check_environment(ENV)
        self.assertEqual(set(REQUIRED_KEYS) - set(environment), set())
        self.assertEqual(environment[SHARED_PATH], "/c/cache/shared")

    def test_it_drops_unset_paths_and_foreign_keys(self) -> None:
        environment = check_environment(ENV)
        self.assertNotIn("INFINITO_CACHE_PACKAGE_HOST_PATH", environment)
        self.assertNotIn("HOME", environment)

    def test_an_unset_required_key_is_refused(self) -> None:
        for key in (WARN_KEY, FLOOR_KEY, CACHES[0].cap_key):
            env = {k: v for k, v in ENV.items() if k != key}
            with self.subTest(key=key), self.assertRaises(KeyError):
                check_environment(env)


class TestTheCheckUnits(unittest.TestCase):
    def setUp(self) -> None:
        self.units = check_units(CHECKOUT, PYTHON, check_environment(ENV), BASE)

    def test_the_service_writes_the_check_file_below_the_cache_base(self) -> None:
        service = self.units[f"{TIMER}.service"]
        self.assertIn(
            f"ExecStart={PYTHON} -m utils.runner.checkmk_local_check "
            f"/c/cache/checkmk/{CHECK_FILE}",
            service,
        )
        self.assertIn(f"WorkingDirectory={CHECKOUT}", service)
        self.assertIn(f"Environment={WARN_KEY}=24h", service)

    def test_the_timer_runs_every_minute(self) -> None:
        self.assertIn("OnUnitActiveSec=1min", self.units[f"{TIMER}.timer"])

    def test_the_check_timer_never_takes_the_idle_timer_name(self) -> None:
        idle = idle_units(CHECKOUT, PYTHON, {})
        self.assertFalse(set(idle) & set(self.units))


class TestTheCheckSetup(unittest.TestCase):
    def test_it_writes_the_units_creates_the_check_dir_and_enables_the_timer(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "cache"
            unit_dir = base / "infra" / "systemd"
            commands = check_setup(["compose"], unit_dir, CHECKOUT, PYTHON, ENV, base)
            written = sorted(path.name for path in unit_dir.iterdir())
            made = check_dir(base).is_dir()
        self.assertEqual(written, [f"{TIMER}.service", f"{TIMER}.timer"])
        self.assertTrue(made)
        self.assertEqual(
            commands[-1][-3:], ["enable", "--now", str(unit_dir / f"{TIMER}.timer")]
        )
        for command in commands:
            self.assertEqual(command[:4], ["compose", "exec", "-T", "runner"])

    def test_an_unset_threshold_writes_nothing(self) -> None:
        env = {k: v for k, v in ENV.items() if k != CRIT_KEY}
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "cache"
            unit_dir = base / "infra" / "systemd"
            with self.assertRaises(KeyError):
                check_setup(["compose"], unit_dir, CHECKOUT, PYTHON, env, base)
            self.assertFalse(unit_dir.exists())
            self.assertFalse(check_dir(base).exists())


if __name__ == "__main__":
    unittest.main()
