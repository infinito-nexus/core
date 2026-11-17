from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.templating.ansible import _trust_as_template

BRIDGE = PROJECT_ROOT / "roles/sys-svc-compose/tasks/utils/network/create/bridge.yml"
DRIFT_NAME = "🛑 Fail on network MTU drift"
DEFAULTED = "(sys_svc_compose_bridge_mtu.stdout | trim or '1500')"
UNDEFAULTED = "sys_svc_compose_bridge_mtu.stdout | trim"


def _drift(tasks: list[dict]) -> dict:
    return next(task for task in tasks if str(task.get("name", "")).startswith(DRIFT_NAME))


def _mutated(old: str, new: str) -> list[dict]:
    """Args:
        old: text that must occur in the real file.
        new: its replacement.

    Returns:
        The real bridge tasks with one textual edit applied.
    """
    source = read_text(str(BRIDGE))
    if old not in source:
        raise AssertionError(f"{BRIDGE} no longer contains {old!r}")
    return load_yaml_str(source.replace(old, new, 1))


def _fails(task: dict, probe: dict, daemon_mtu: object) -> bool:
    """Args:
        task: the drift fail task.
        probe: the registered result of the MTU inspect task.
        daemon_mtu: the value SYS_DOCKER_DAEMONM_MTU holds.

    Returns:
        Whether every condition of the task holds, so the deploy stops.
    """
    templar = Templar(
        loader=DataLoader(),
        variables={
            "sys_svc_compose_bridge_mtu": probe,
            "SYS_DOCKER_DAEMONM_MTU": daemon_mtu,
        },
    )
    return all(
        templar.template(_trust_as_template("{{ (" + condition + ") | bool }}"))
        for condition in task["when"]
    )


def _inspected(stdout: str) -> dict:
    return {"stdout": stdout, "changed": False, "skipped": False}


class TestBridgeMtuDrift(unittest.TestCase):
    def setUp(self) -> None:
        self.task = _drift(load_yaml_any(str(BRIDGE), default_if_missing=[]))

    def test_a_bridge_without_the_mtu_option_matches_a_1500_daemon(self):
        self.assertFalse(_fails(self.task, _inspected(""), 1500))

    def test_a_blank_probe_with_whitespace_matches_a_1500_daemon(self):
        self.assertFalse(_fails(self.task, _inspected(" \n"), "1500"))

    def test_a_bridge_without_the_mtu_option_drifts_from_a_1450_daemon(self):
        self.assertTrue(_fails(self.task, _inspected(""), 1450))

    def test_a_bridge_at_the_daemon_mtu_passes(self):
        self.assertFalse(_fails(self.task, _inspected("1450"), 1450))

    def test_a_bridge_at_another_mtu_drifts(self):
        self.assertTrue(_fails(self.task, _inspected("1500"), 1450))

    def test_a_skipped_probe_never_fails(self):
        self.assertFalse(_fails(self.task, {"skipped": True, "changed": False}, 1450))


class TestNegativeControl(unittest.TestCase):
    def test_without_the_default_a_blank_probe_fails_a_1500_daemon(self):
        task = _drift(_mutated(DEFAULTED, UNDEFAULTED))
        self.assertTrue(_fails(task, _inspected(""), 1500))


if __name__ == "__main__":
    unittest.main()
