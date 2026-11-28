"""The swarm pre-create of a stream relay network, run against mocked probes.

Evaluates the conditions and the argv of ``tasks/utils/network/create/relay.yml``
the way Ansible does, for a network that is absent, present as required,
present with a drift, and a probe that fails.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

RELAY_TASKS = (
    PROJECT_ROOT / "roles/sys-svc-compose/tasks/utils/network/create/relay.yml"
)
SWARM_HANDLERS = PROJECT_ROOT / "roles/sys-svc-compose/handlers/swarm.yml"
SUBNET = "192.168.105.48/28"
RELAY = {"name": "openldap-relay", "subnet": SUBNET, "stack": "openldap"}
MATCHING: dict[str, Any] = {
    "Name": "openldap-relay",
    "Driver": "overlay",
    "Scope": "swarm",
    "Attachable": True,
    "Options": {"encrypted": "true"},
    "IPAM": {"Config": [{"Subnet": SUBNET, "Gateway": "192.168.105.49"}]},
    "Labels": {
        "com.docker.compose.network": "openldap-relay",
        "com.docker.compose.project": "openldap",
        "com.docker.stack.namespace": "openldap",
    },
}
LABELS = [
    "--label",
    "com.docker.compose.network=openldap-relay",
    "--label",
    "com.docker.compose.project=openldap",
    "--label",
    "com.docker.stack.namespace=openldap",
]


def _conditions(task: dict) -> list[str]:
    conditions = task.get("when", [])
    return [conditions] if isinstance(conditions, str) else list(conditions)


def _tasks() -> list[dict]:
    """The tasks in run order, each block child carrying its block's ``when``."""
    flat: list[dict] = []
    for task in load_yaml_any(str(RELAY_TASKS), default_if_missing=[]):
        if "block" not in task:
            flat.append(task)
            continue
        flat.extend(
            {**child, "when": _conditions(task) + _conditions(child)}
            for child in task["block"]
        )
    return flat


def _task(prefix: str) -> dict:
    return next(task for task in _tasks() if task["name"].startswith(prefix))


def _render(expression: str, facts: dict) -> Any:
    templar = Templar(loader=DataLoader(), variables=facts)
    return templar.template(_trust_as_template(expression))


def _holds(task: dict, facts: dict) -> bool:
    return all(_render("{{ (" + c + ") | bool }}", facts) for c in _conditions(task))


def _ls(*names: str) -> dict:
    return {
        "rc": 0,
        "stdout_lines": [
            json.dumps({"Name": name, "Driver": "overlay"}) for name in names
        ],
    }


def _flow(ls: dict, network: dict | None = None, *, encryption: bool = True) -> dict:
    """Walk the task file the way one play run does.

    Args:
      ls: the registered result of the name listing.
      network: the object ``network inspect`` prints, when the network exists.
      encryption: the value of ``swarm.network.encryption``.

    Returns:
      ``present``, ``inspected``, ``drift_holds`` (None when skipped) and
      ``create`` (the argv, None when skipped).
    """
    facts: dict[str, Any] = {
        "stream_relay": RELAY,
        "swarm": {"network": {"encryption": encryption}},
        "sys_svc_compose_relay_ls": ls,
    }
    note = _task("🔎 Note")["ansible.builtin.set_fact"]
    facts["sys_svc_compose_relay_present"] = _render(
        note["sys_svc_compose_relay_present"], facts
    )
    inspected = _holds(_task("🔍 Inspect"), facts)
    if inspected:
        facts["sys_svc_compose_relay_inspect"] = {
            "rc": 0,
            "stdout": json.dumps(network),
        }
    parse = _task("📥 Parse")
    if _holds(parse, facts):
        facts["sys_svc_compose_relay"] = _render(
            parse["ansible.builtin.set_fact"]["sys_svc_compose_relay"], facts
        )
    drift = _task("🛑 Fail on drift")
    drift_holds = None
    if _holds(drift, facts):
        drift_holds = all(
            _render("{{ (" + c + ") | bool }}", facts)
            for c in drift["ansible.builtin.assert"]["that"]
        )
    create = _task("✅ Create")
    argv = None
    if _holds(create, facts):
        argv = _render(create["vars"]["sys_svc_compose_relay_create_argv"], facts)
    return {
        "present": bool(facts["sys_svc_compose_relay_present"]),
        "inspected": inspected,
        "drift_holds": drift_holds,
        "create": argv,
    }


def _drifted(**changes: Any) -> dict:
    return {**MATCHING, **changes}


class TestAnAbsentNetworkIsCreated(unittest.TestCase):
    def test_an_empty_listing_creates_an_encrypted_attachable_overlay(self):
        result = _flow(_ls())
        self.assertFalse(result["present"])
        self.assertFalse(result["inspected"])
        self.assertIsNone(result["drift_holds"])
        self.assertEqual(
            result["create"],
            [
                "container",
                "network",
                "create",
                "--driver",
                "overlay",
                "--attachable",
                "--scope",
                "swarm",
                "--subnet",
                SUBNET,
                "--opt",
                "encrypted=true",
                *LABELS,
                "openldap-relay",
            ],
        )

    def test_without_encryption_the_option_is_left_out(self):
        argv = _flow(_ls(), encryption=False)["create"]
        self.assertNotIn("--opt", argv)
        self.assertFalse(any("encrypted" in str(arg) for arg in argv))

    def test_a_network_whose_name_only_contains_the_relay_name_counts_as_absent(self):
        result = _flow(_ls("openldap-relay-old", "x-openldap-relay"))
        self.assertFalse(result["present"])
        self.assertIsNotNone(result["create"])


class TestAPresentNetworkIsCheckedNotCreated(unittest.TestCase):
    def test_a_matching_network_passes_and_is_not_created_again(self):
        result = _flow(_ls("openldap-relay"), MATCHING)
        self.assertEqual(
            result,
            {"present": True, "inspected": True, "drift_holds": True, "create": None},
        )

    def test_an_unencrypted_network_matches_a_deploy_without_encryption(self):
        network = _drifted(Options={})
        self.assertTrue(
            _flow(_ls("openldap-relay"), network, encryption=False)["drift_holds"]
        )

    def test_every_drift_fails(self):
        drifts = {
            "driver": _drifted(Driver="bridge"),
            "scope": _drifted(Scope="local"),
            "attachable": _drifted(Attachable=False),
            "encryption off": _drifted(Options={}),
            "encryption options null": _drifted(Options=None),
            "subnet": _drifted(IPAM={"Config": [{"Subnet": "10.0.9.0/24"}]}),
            "no ipam": _drifted(IPAM={"Config": None}),
            "stack": _drifted(Labels={"com.docker.stack.namespace": "openresty"}),
            "no labels": _drifted(Labels=None),
        }
        for name, network in drifts.items():
            with self.subTest(drift=name):
                result = _flow(_ls("openldap-relay"), network)
                self.assertFalse(result["drift_holds"])
                self.assertIsNone(result["create"])

    def test_encryption_on_a_deploy_without_it_is_a_drift(self):
        self.assertFalse(
            _flow(_ls("openldap-relay"), MATCHING, encryption=False)["drift_holds"]
        )


class TestTheHandlerLooksUpRelaysOnlyInSwarm(unittest.TestCase):
    @staticmethod
    def _loop() -> str:
        handlers = load_yaml_any(str(SWARM_HANDLERS), default_if_missing=[])
        handler = next(
            task
            for task in handlers
            if "create/relay.yml" in str(task.get("ansible.builtin.include_tasks"))
        )
        return handler["loop"]

    def test_a_compose_flush_never_runs_the_lookup(self):
        self.assertEqual(_render(self._loop(), {"IS_SWARM_MODE": False}), [])

    def test_a_swarm_flush_runs_it(self):
        with self.assertRaisesRegex(Exception, "stream_relay_networks"):
            _render(self._loop(), {"IS_SWARM_MODE": True, "DEPLOYMENT_MODE": "swarm"})


class TestAFailedProbeStopsTheRun(unittest.TestCase):
    def test_neither_probe_tolerates_a_failure(self):
        for prefix in ("🔍 List", "🔍 Inspect"):
            with self.subTest(task=prefix):
                task = _task(prefix)
                self.assertNotIn("failed_when", task)
                self.assertNotIn("ignore_errors", task)

    def test_the_listing_is_the_only_source_of_absence(self):
        self.assertEqual(
            _task("🔍 List")["ansible.builtin.command"]["argv"][:3],
            ["container", "network", "ls"],
        )


if __name__ == "__main__":
    unittest.main()
