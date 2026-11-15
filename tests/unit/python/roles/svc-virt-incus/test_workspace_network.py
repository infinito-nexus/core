from __future__ import annotations

import copy
import ipaddress
import unittest

from ansible.errors import AnsibleFilterError

from tests.utils.ansible_assert import assert_task, holds, message
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from ._incus import FILTERS, INCUS, NFTABLES, ROLE, VARS, dropped, evaluate, ruleset

CORE = ROLE / "tasks" / "00_core.yml"
WORKSPACE_TASKS = ROLE / "tasks" / "workspace.yml"
APPLY_TASKS = ROLE / "tasks" / "workspace" / "apply.yml"
WORKSPACE_TEXT = "".join(
    read_text(str(path))
    for path in (WORKSPACE_TASKS, *sorted((ROLE / "tasks" / "workspace").glob("*.yml")))
)
TASKS = load_yaml_any(str(WORKSPACE_TASKS), default_if_missing=[])
APPLY = load_yaml_any(str(APPLY_TASKS), default_if_missing=[])
GUARD = assert_task(CORE, "🛑 Refuse workspaces without a routed subnet")
A = "0c6f7a52-3d1e-4b8a-9f00-2a7b1c9d4e5f"
B = "7d2e9b14-55aa-4c3d-8e21-90f1a6b3c7d8"
SUBNET = {"ipv4": "198.51.100.0/24", "ipv6": "2001:db8:62::/48"}
WORKSPACES = {**INCUS["workspaces"], "enabled": True, "subnet": SUBNET}
AGENTS = {
    "name": "agentbr0",
    "config": {"ipv4.address": INCUS["network"]["ipv4"], "ipv6.address": "none"},
}


def _apply(name: str) -> dict:
    return next(task for task in APPLY if task.get("name", "").startswith(name))


def _bridge_task(workspace: str, networks: list) -> dict:
    bridge = FILTERS.incus_workspace_network(workspace, WORKSPACES, networks)
    return {"name": bridge["name"], "config": dict(bridge["config"])}


def route_findings(bridges: list[dict]) -> list[str]:
    """Args:
        bridges: ``{"name", "config"}`` of each workspace bridge.

    Returns:
        Every bridge that does not route its own public slice.
    """
    findings = []
    seen: list = []
    for bridge in bridges:
        config = bridge["config"]
        for family, key, prefix in (
            ("ipv4", "ipv4.address", 28),
            ("ipv6", "ipv6.address", 64),
        ):
            interface = ipaddress.ip_interface(config[key])
            if not interface.network.subnet_of(ipaddress.ip_network(SUBNET[family])):
                findings.append(
                    f"{bridge['name']} {key} {config[key]} leaves the subnet"
                )
            if interface.network.prefixlen != prefix:
                findings.append(f"{bridge['name']} {key} is no /{prefix}")
            if any(interface.network.overlaps(other) for other in seen):
                findings.append(f"{bridge['name']} {key} overlaps another bridge")
            seen.append(interface.network)
        findings.extend(
            f"{bridge['name']} {key} is {config.get(key)}"
            for key in ("ipv4.nat", "ipv6.nat")
            if config.get(key) != "false"
        )
    return findings


class TestWorkspaceNetwork(unittest.TestCase):
    def test_workspace_bridges_route_public_addresses(self):
        first = _bridge_task(A, [AGENTS])
        created = copy.deepcopy(first)
        second = _bridge_task(B, [AGENTS, created])
        self.assertEqual(route_findings([first, second]), [])
        self.assertEqual(first["config"]["ipv4.address"], "198.51.100.1/28")
        self.assertEqual(second["config"]["ipv4.address"], "198.51.100.17/28")
        self.assertEqual(first["config"]["user.infinito.workspace"], A)
        again = FILTERS.incus_workspace_network(A, WORKSPACES, [AGENTS, created])
        self.assertTrue(again["exists"])
        self.assertTrue(again["converged"])
        self.assertEqual(again["config"], first["config"])
        drifted = copy.deepcopy(created)
        drifted["config"]["ipv4.nat"] = "true"
        self.assertFalse(
            FILTERS.incus_workspace_network(A, WORKSPACES, [drifted])["converged"]
        )
        self.assertNotIn("network forward", WORKSPACE_TEXT)
        self.assertNotIn("nat=true", WORKSPACE_TEXT)
        create = _apply("🌐 Create the bridge")
        argv = evaluate(
            create["ansible.builtin.command"]["argv"],
            {
                "svc_virt_incus_ws_bridge": FILTERS.incus_workspace_network(
                    A, WORKSPACES, [AGENTS]
                )
            },
        )
        self.assertEqual(
            argv[:6], ["incus", "network", "create", first["name"], "--type", "bridge"]
        )
        self.assertIn("ipv4.nat=false", argv)
        self.assertIn("ipv6.nat=false", argv)

    def test_negative_control_a_nat_bridge_is_caught(self):
        bridge = _bridge_task(A, [AGENTS])
        bridge["config"]["ipv6.nat"] = "true"
        self.assertEqual(
            route_findings([bridge]), [f"{bridge['name']} ipv6.nat is true"]
        )
        twin = _bridge_task(B, [AGENTS])
        self.assertIn(
            f"{twin['name']} ipv4.address overlaps another bridge",
            route_findings([bridge, twin]),
        )

    def test_a_bridge_name_of_another_workspace_is_refused(self):
        twin = "0c6f7a52-3d1e-0000-0000-000000000000"
        held = {
            "name": FILTERS.incus_workspace_bridge(A, "wsbr"),
            "config": {"user.infinito.workspace": twin},
        }
        with self.assertRaises(AnsibleFilterError):
            FILTERS.incus_workspace_network(A, WORKSPACES, [held])
        self.assertLessEqual(len(FILTERS.incus_workspace_bridge(A, "wsbr")), 15)

    def test_a_full_subnet_is_refused(self):
        small = {
            **WORKSPACES,
            "subnet": {"ipv4": "198.51.100.0/28", "ipv6": SUBNET["ipv6"]},
        }
        held = {
            "name": "wsbrother",
            "config": {"ipv4.address": "198.51.100.1/28", "ipv6.address": "none"},
        }
        with self.assertRaises(AnsibleFilterError):
            FILTERS.incus_workspace_network(A, small, [held])

    def test_the_deploy_refuses_workspaces_without_a_subnet(self):
        def scope(enabled: bool, ipv4: str, ipv6: str) -> dict:
            return {
                "INCUS_WORKSPACES": {
                    "enabled": enabled,
                    "subnet": {"ipv4": ipv4, "ipv6": ipv6},
                },
                "inventory_hostname": "echoserver",
            }

        self.assertTrue(holds(GUARD, scope(True, SUBNET["ipv4"], SUBNET["ipv6"])))
        self.assertTrue(holds(GUARD, scope(False, "", "")))
        self.assertFalse(holds(GUARD, scope(True, "", SUBNET["ipv6"])))
        self.assertFalse(holds(GUARD, scope(True, SUBNET["ipv4"], "")))
        self.assertIn("subnet", message(GUARD, scope(True, "", "")))
        names = [
            task.get("name", "")
            for task in load_yaml_any(str(CORE), default_if_missing=[])
        ]
        self.assertLess(
            names.index(GUARD["name"]), names.index("🚀 Start the Incus daemon")
        )
        check = TASKS[0]["ansible.builtin.assert"]["that"]
        self.assertIn("INCUS_WORKSPACES.subnet.ipv4 | length > 0", check)
        self.assertIn("INCUS_WORKSPACES.subnet.ipv6 | length > 0", check)
        with self.assertRaises(AnsibleFilterError):
            FILTERS.incus_workspace_network(
                A, {**WORKSPACES, "subnet": {"ipv4": SUBNET["ipv4"], "ipv6": ""}}, []
            )

    def test_negative_control_a_guard_without_the_ipv6_check_is_caught(self):
        mutant = copy.deepcopy(GUARD)
        mutant["ansible.builtin.assert"]["that"] = [
            "(not (INCUS_WORKSPACES.enabled | bool)) or (INCUS_WORKSPACES.subnet.ipv4 | length > 0)"
        ]
        self.assertTrue(
            holds(
                mutant,
                {
                    "INCUS_WORKSPACES": {
                        "enabled": True,
                        "subnet": {"ipv4": SUBNET["ipv4"], "ipv6": ""},
                    }
                },
            )
        )

    def test_workspace_bridges_forward_nothing_to_each_other(self):
        text = ruleset(NFTABLES, [], WORKSPACES)
        a = FILTERS.incus_workspace_bridge(A, "wsbr")
        b = FILTERS.incus_workspace_bridge(B, "wsbr")
        self.assertTrue(dropped(text, "forward", iif=a, oif=b))
        self.assertTrue(dropped(text, "forward", iif=a, oif="agentbr0"))
        self.assertTrue(dropped(text, "forward", iif="agentbr0", oif=b))
        self.assertFalse(dropped(text, "forward", iif=a, oif="eth0"))
        self.assertFalse(dropped(text, "forward", iif="eth0", oif=a))

    def test_the_project_holds_virtual_machines_only_under_the_agent_restrictions(self):
        restrictions = evaluate(
            VARS["INCUS_WORKSPACE_RESTRICTIONS"],
            {"INCUS_PROJECT_CONFIG": VARS["INCUS_PROJECT_CONFIG"]},
        )
        bridge = FILTERS.incus_workspace_bridge(A, "wsbr")
        project = FILTERS.incus_workspace_project(bridge, WORKSPACES, restrictions)
        agents = {
            key: value
            for key, value in VARS["INCUS_PROJECT_CONFIG"].items()
            if key.startswith("restricted") and key != "restricted.networks.access"
        }
        self.assertEqual({key: project[key] for key in agents}, agents)
        self.assertEqual(project["limits.containers"], "0")
        self.assertEqual(project["restricted.networks.access"], bridge)
        limits = WORKSPACES["limits"]
        self.assertEqual(
            {key: project[f"limits.{key}"] for key in limits},
            {key: str(value) for key, value in limits.items()},
        )
        profile = FILTERS.incus_workspace_profile(A, bridge, "agents", WORKSPACES)
        nic = profile["devices"]["eth0"]
        for key in (
            "security.mac_filtering",
            "security.ipv4_filtering",
            "security.ipv6_filtering",
        ):
            self.assertEqual(nic[key], "true", key)
        self.assertEqual(nic["network"], bridge)
        self.assertEqual(profile["devices"]["root"]["pool"], "agents")
        self.assertEqual(set(profile["config"]), {"limits.cpu", "limits.memory"})


if __name__ == "__main__":
    unittest.main()
