from __future__ import annotations

import unittest

from utils.agents import workspace

HOSTS = frozenset({"hypervisor"})
RUNTIMES = frozenset({"claude-code"})


def _agent(**fields) -> dict:
    agent = {
        "runtime": "claude-code",
        "lifecycle": "on_demand",
        "firewall_roles": ["autonomous-contributor"],
        "quotas": {"requests_per_minute": 60},
    }
    agent.update(fields)
    if "workspace" in fields:
        agent["workspace"] = {
            "kind": "server",
            "model_access": "gateway",
            **fields["workspace"],
        }
    return agent


def _vm(**fields) -> dict:
    ws = {
        "kind": "proxmox",
        "target": "hypervisor",
        "resources": {"vcpu": 2, "memory": "4g", "disk": "32g"},
    }
    ws.update(fields)
    return ws


class TestRequired(unittest.TestCase):
    def _raw(self, ws: dict) -> list[str]:
        agent = {"runtime": "hermes", "firewall_roles": ["robot"], "workspace": ws}
        return workspace.problems(agent, frozenset(), frozenset())

    def test_empty_workspace_is_refused(self):
        self.assertEqual(
            self._raw({}),
            ["workspace.kind is required", "workspace.model_access is required"],
        )

    def test_kind_and_model_access_must_both_be_set(self):
        self.assertEqual(
            self._raw({"kind": "server"}), ["workspace.model_access is required"]
        )
        self.assertEqual(self._raw({"kind": "server", "model_access": "gateway"}), [])

    def test_vm_size_without_resources_raises_a_named_error(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.vm_size(None)
        with self.assertRaises(workspace.WorkspaceError):
            workspace.vm_size({"vcpu": 2})


class TestInventoryHosts(unittest.TestCase):
    def test_collects_hosts_of_every_group(self):
        inventory = {
            "all": {
                "hosts": {"a": None},
                "children": {
                    "g1": {"hosts": {"b": None}},
                    "g2": {"children": {"g3": {"hosts": {"c": None}}}},
                },
            }
        }
        self.assertEqual(workspace.inventory_hosts(inventory), {"a", "b", "c"})


class TestProblems(unittest.TestCase):
    def _problems(self, agent: dict) -> list[str]:
        return workspace.problems(agent, HOSTS, RUNTIMES)

    def test_valid_vm_workspace_passes(self):
        self.assertEqual(self._problems(_agent(workspace=_vm())), [])

    def test_quotas_keep_their_meaning_next_to_resources(self):
        agent = _agent(workspace=_vm())
        self.assertEqual(self._problems(agent), [])
        self.assertEqual(agent["quotas"], {"requests_per_minute": 60})

    def test_every_kind_is_known(self):
        for kind in ("host", "server", "agentbox", "incus", "proxmox"):
            self.assertIn(kind, workspace.WORKSPACE_KINDS)
        self.assertTrue(self._problems(_agent(workspace={"kind": "lxc"})))

    def test_agentbox_needs_a_box_runtime(self):
        self.assertTrue(self._problems(_agent(workspace={"kind": "agentbox"})))
        for runtime in ("sysbox", "kata"):
            self.assertEqual(
                self._problems(
                    _agent(workspace={"kind": "agentbox", "box_runtime": runtime})
                ),
                [],
            )
        self.assertTrue(
            self._problems(
                _agent(workspace={"kind": "agentbox", "box_runtime": "runc"})
            )
        )

    def test_box_runtime_only_for_agentbox(self):
        self.assertTrue(
            self._problems(_agent(workspace={"kind": "server", "box_runtime": "kata"}))
        )

    def test_settings_mode_is_a_known_mode(self):
        for mode in ("autopilot", "copilot", "zero-trust"):
            self.assertEqual(
                self._problems(_agent(workspace={"settings_mode": mode})), []
            )
        self.assertTrue(self._problems(_agent(workspace={"settings_mode": "yolo"})))

    def test_host_kind_only_for_interactive_roles(self):
        self.assertTrue(self._problems(_agent(workspace={"kind": "host"})))
        self.assertEqual(
            self._problems(
                _agent(workspace={"kind": "host"}, firewall_roles=["interactive"])
            ),
            [],
        )

    def test_vm_target_must_be_an_inventory_host(self):
        self.assertTrue(self._problems(_agent(workspace=_vm(target="elsewhere"))))
        self.assertTrue(self._problems(_agent(workspace=_vm(target=None))))

    def test_vm_refused_for_always_on(self):
        self.assertTrue(self._problems(_agent(workspace=_vm(), lifecycle="always_on")))

    def test_vm_refused_for_runtime_outside_template(self):
        self.assertTrue(self._problems(_agent(workspace=_vm(), runtime="openclaw")))

    def test_vm_resources_parse(self):
        self.assertTrue(
            self._problems(
                _agent(
                    workspace=_vm(resources={"vcpu": 2, "memory": "lots", "disk": "1g"})
                )
            )
        )
        self.assertTrue(
            self._problems(
                _agent(
                    workspace=_vm(
                        resources={"vcpu": 2, "memory": "1g", "disk": "1g", "gpu": 1}
                    )
                )
            )
        )

    def test_vm_size_in_bytes(self):
        self.assertEqual(
            workspace.vm_size({"vcpu": "2", "memory": "4g", "disk": "32GiB"}),
            {"vcpu": 2, "memory": 4 * 10**9, "disk": 32 * 1024**3},
        )

    def test_model_access_values(self):
        self.assertEqual(
            self._problems(_agent(workspace=_vm(model_access="login"))), []
        )
        self.assertTrue(self._problems(_agent(workspace={"model_access": "token"})))

    def test_login_mode_is_refused_outside_a_vm_kind(self):
        for ws in (
            {"model_access": "login"},
            {"kind": "agentbox", "box_runtime": "kata", "model_access": "login"},
        ):
            problems = self._problems(_agent(workspace=ws))
            self.assertTrue(
                any(
                    "model_access login applies to incus and proxmox only" in p
                    for p in problems
                ),
                problems,
            )
        self.assertEqual(
            self._problems(_agent(workspace=_vm(model_access="login"))), []
        )


if __name__ == "__main__":
    unittest.main()
