import unittest

from plugins.filter.agent_vm_capacity import (
    FilterModule,
    agent_login_notice,
    agent_vm_capacity,
    agent_vm_problems,
    agent_vm_sizes,
    agent_vm_stray_targets,
)
from utils import PROJECT_ROOT
from utils.agents.workspace import WorkspaceError
from utils.cache.yaml import load_yaml_any

CAPACITY_TASKS = PROJECT_ROOT / "roles/svc-ai-agent-broker/tasks/utils/vm/capacity.yml"
AGENT_TASKS = PROJECT_ROOT / "roles/svc-ai-agent-broker/tasks/utils/vm/agents.yml"
BROKER_TASKS = PROJECT_ROOT / "roles/svc-ai-agent-broker/tasks/00_core.yml"
STRAY_CHECK = (
    "🛑 Refuse an agent VM workspace whose target runs no hypervisor of its kind"
)


def _includes(tasks_file, included) -> bool:
    tasks = load_yaml_any(str(tasks_file), default_if_missing=[])
    return any(
        included in str(task.get("ansible.builtin.include_tasks", "")) for task in tasks
    )


GIB = 1024**3
WORKSPACES = [
    {"kind": "server", "model_access": "gateway"},
    {
        "kind": "proxmox",
        "model_access": "gateway",
        "target": "dc1",
        "resources": {"vcpu": 4, "memory": "8GiB", "disk": "64GiB"},
    },
    {
        "kind": "proxmox",
        "model_access": "gateway",
        "target": "dc2",
        "resources": {"vcpu": 16, "memory": "64GiB", "disk": "512GiB"},
    },
]
MOUNTS = [
    {"mount": "/", "size_available": 10 * GIB},
    {"mount": "/var/lib/vz", "size_available": 200 * GIB},
]
RESERVE = {"memory": "2GiB", "disk": "8GiB"}
OVERHEAD = {"cpus": 1, "memory": "2GiB"}


def _capacity(
    free_memory,
    limits,
    max_running=1,
    warm_pool=1,
    running=0,
    pool_size="",
    pool_used=0,
    own_disk=0,
    ws=None,
    mounts=None,
):
    return agent_vm_capacity(
        WORKSPACES if ws is None else ws,
        "proxmox",
        "dc1",
        max_running,
        warm_pool,
        RESERVE,
        free_memory,
        running,
        MOUNTS if mounts is None else mounts,
        "/var/lib/vz/images",
        pool_size,
        pool_used,
        own_disk,
        OVERHEAD,
        limits,
    )


def _agent(workspace: dict, runtime: str = "claude-code") -> dict:
    return {
        "runtime": runtime,
        "lifecycle": "on_demand",
        "firewall_roles": ["autonomous-contributor"],
        "workspace": workspace,
    }


class TestAgentVmCapacity(unittest.TestCase):
    def test_filters_registered(self):
        self.assertEqual(
            FilterModule().filters(),
            {
                "agent_login_notice": agent_login_notice,
                "agent_vm_capacity": agent_vm_capacity,
                "agent_vm_problems": agent_vm_problems,
                "agent_vm_stray_targets": agent_vm_stray_targets,
            },
        )

    def test_sizes_only_of_this_host_and_kind(self):
        sizes = agent_vm_sizes(WORKSPACES, "proxmox", "dc1")
        self.assertEqual(sizes, [{"vcpu": 4, "memory": 8 * GIB, "disk": 64 * GIB}])
        self.assertEqual(agent_vm_sizes(WORKSPACES, "incus", "dc1"), [])

    def test_enough_host_and_limits_pass(self):
        self.assertEqual(_capacity(18 * GIB, {"cpus": "9", "mem_limit": "18GiB"}), [])

    def test_free_memory_below_demand_plus_reserve_is_refused(self):
        found = _capacity(17 * GIB, {})
        self.assertEqual(len(found), 1)
        self.assertIn("free memory", found[0])

    def test_memory_of_the_roles_own_running_vms_counts_as_free(self):
        self.assertEqual(_capacity(10 * GIB, {}, running=8 * GIB), [])
        self.assertTrue(_capacity(10 * GIB, {}, running=0))

    def test_space_of_the_roles_own_vm_disks_counts_as_free(self):
        self.assertEqual(
            _capacity(34 * GIB, {}, max_running=2, warm_pool=2, own_disk=64 * GIB), []
        )

    def test_negative_control_without_own_disks_the_same_host_is_refused(self):
        found = _capacity(34 * GIB, {}, max_running=2, warm_pool=2, own_disk=0)
        self.assertEqual(len(found), 1, found)
        self.assertIn("free disk", found[0])

    def test_a_fixed_pool_holds_the_demand_without_the_reserve(self):
        roomy = [{"mount": "/var/lib/vz", "size_available": 1000 * GIB}]
        self.assertEqual(_capacity(18 * GIB, {}, pool_size="128GiB", mounts=roomy), [])
        found = _capacity(18 * GIB, {}, pool_size="127GiB", mounts=roomy)
        self.assertEqual(len(found), 1, found)
        self.assertIn("fixed storage pool", found[0])

    def test_own_disks_count_back_inside_a_fixed_pool(self):
        roomy = [{"mount": "/var/lib/vz", "size_available": 1000 * GIB}]
        pool = {"pool_size": "200GiB", "pool_used": 100 * GIB, "mounts": roomy}
        self.assertEqual(_capacity(18 * GIB, {}, own_disk=40 * GIB, **pool), [])
        found = _capacity(18 * GIB, {}, own_disk=0, **pool)
        self.assertTrue(any("fixed storage pool" in line for line in found), found)

    def test_storage_is_read_from_the_mount_holding_the_disks(self):
        found = _capacity(18 * GIB, {}, max_running=2, warm_pool=2)
        self.assertTrue(any("free disk" in line for line in found), found)

    def test_a_fixed_pool_size_bounds_the_disk_not_the_free_host_disk(self):
        self.assertEqual(_capacity(18 * GIB, {}, pool_size="200GiB"), [])
        found = _capacity(18 * GIB, {}, pool_size="100GiB")
        self.assertTrue(any("free disk" in line for line in found), found)

    def test_the_pool_counts_only_its_free_space(self):
        found = _capacity(18 * GIB, {}, pool_size="200GiB", pool_used=100 * GIB)
        self.assertTrue(any("free disk" in line for line in found), found)

    def test_a_large_pool_on_a_full_filesystem_is_refused(self):
        full = [{"mount": "/var/lib/vz", "size_available": 5 * GIB}]
        found = agent_vm_capacity(
            WORKSPACES,
            "proxmox",
            "dc1",
            1,
            1,
            RESERVE,
            18 * GIB,
            0,
            full,
            "/var/lib/vz/images",
            "200GiB",
            0,
            0,
            OVERHEAD,
            {},
        )
        self.assertTrue(any("free disk" in line for line in found), found)

    def test_a_negative_warm_pool_is_refused(self):
        with self.assertRaises(ValueError):
            _capacity(18 * GIB, {}, warm_pool=-1)

    def test_docker_mem_limit_suffixes_are_binary(self):
        self.assertEqual(_capacity(18 * GIB, {"cpus": "9", "mem_limit": "18g"}), [])
        self.assertEqual(_capacity(18 * GIB, {"cpus": "9", "mem_limit": "18gb"}), [])
        found = _capacity(18 * GIB, {"cpus": "9", "mem_limit": "17g"})
        self.assertTrue(any("container" in line for line in found), found)

    def test_container_limits_below_demand_plus_overhead_are_refused(self):
        found = _capacity(18 * GIB, {"cpus": "8", "mem_limit": "16GiB"})
        self.assertEqual(len(found), 2)
        self.assertTrue(all("container" in line for line in found))

    def test_vm_override_without_resources_raises_a_named_error(self):
        broken = [{"kind": "proxmox", "model_access": "gateway", "target": "dc1"}]
        with self.assertRaises(WorkspaceError):
            _capacity(18 * GIB, {}, ws=broken)


class TestAgentVmProblems(unittest.TestCase):
    def test_merged_override_breaking_the_contract_is_reported(self):
        agents = {
            "ok": _agent(WORKSPACES[1]),
            "bad": _agent(
                {"kind": "proxmox", "model_access": "gateway", "target": "dc1"}
            ),
            "elsewhere": _agent({"kind": "proxmox", "target": "dc2"}),
        }
        problems = agent_vm_problems(agents, "proxmox", "dc1", ["dc1", "dc2"])
        self.assertTrue(problems)
        self.assertTrue(all(p.startswith("bad: ") for p in problems), problems)

    def test_misspelt_target_is_refused_once_for_the_play(self):
        agents = {
            "typo": _agent({**WORKSPACES[1], "target": "dc1-typo"}),
            "ok": _agent(WORKSPACES[1]),
            "server": _agent(WORKSPACES[0]),
        }
        stray = agent_vm_stray_targets(agents, {"proxmox": ["dc1", "dc2"], "incus": []})
        self.assertEqual(len(stray), 1)
        self.assertTrue(stray[0].startswith("typo: "), stray)
        tasks = load_yaml_any(str(AGENT_TASKS), default_if_missing=[])
        names = [task.get("name", "") for task in tasks]
        check = tasks[names.index(STRAY_CHECK)]
        self.assertIs(check["run_once"], True)
        for group in ("groups.get('svc-virt-incus')", "groups.get('web-app-proxmox')"):
            self.assertIn(group, check["vars"]["vm_capacity_stray"])

    def test_the_hypervisor_and_the_broker_deploy_run_the_target_check(self):
        for tasks_file in (CAPACITY_TASKS, BROKER_TASKS):
            with self.subTest(tasks=tasks_file.name):
                self.assertTrue(_includes(tasks_file, "tasks/utils/vm/agents.yml"))

    def test_target_of_the_wrong_kind_is_refused(self):
        agents = {"wrong": _agent({**WORKSPACES[1], "kind": "incus"})}
        stray = agent_vm_stray_targets(agents, {"proxmox": ["dc1"], "incus": ["inc1"]})
        self.assertEqual(len(stray), 1)
        self.assertIn("runs no incus hypervisor", stray[0])

    def test_runtime_outside_the_template_is_reported(self):
        agents = {"hermes": _agent(WORKSPACES[1], runtime="hermes")}
        problems = agent_vm_problems(agents, "proxmox", "dc1", ["dc1"])
        self.assertTrue(any("not in the VM template" in p for p in problems))

    def test_deploy_checks_the_contract_before_the_capacity(self):
        tasks = load_yaml_any(str(CAPACITY_TASKS), default_if_missing=[])
        names = [task.get("name", "") for task in tasks]
        contract = names.index(
            "🛑 Refuse an agent VM workspace that breaks the workspace contract"
        )
        capacity = names.index(
            "🛑 Refuse a VM host that cannot hold the warm pool and the running agents"
        )
        self.assertLess(contract, capacity)
        self.assertIn(
            "agent_vm_problems", tasks[contract]["vars"]["vm_capacity_problems"]
        )
        self.assertLess(
            names.index(
                "📋 Collect the agent configs {{ inventory_hostname }} may serve"
            ),
            contract,
        )
        collect = load_yaml_any(str(AGENT_TASKS), default_if_missing=[])[1]
        self.assertIn(
            "'workspace': lookup('agent_config', item, 'workspace')", str(collect)
        )


class TestAgentLoginNotice(unittest.TestCase):
    def test_gateway_mode_prints_nothing(self):
        self.assertEqual(agent_login_notice(WORKSPACES, "proxmox", "dc1"), "")

    def test_login_mode_names_what_no_longer_applies(self):
        login = [{**WORKSPACES[1], "model_access": "login"}, WORKSPACES[2]]
        notice = agent_login_notice(login, "proxmox", "dc1")
        for needle in (
            "model list",
            "quotas",
            "spend log",
            "until the operator revokes",
        ):
            self.assertIn(needle, notice)
        self.assertTrue(notice.startswith("1 agent VM"))
        self.assertEqual(agent_login_notice(login, "proxmox", "dc2"), "")

    def test_deploy_prints_the_notice(self):
        tasks = load_yaml_any(str(CAPACITY_TASKS), default_if_missing=[])
        debug = [task for task in tasks if "ansible.builtin.debug" in task]
        self.assertEqual(len(debug), 1)
        self.assertIn(
            "agent_login_notice", debug[0]["vars"]["vm_capacity_login_notice"]
        )
        self.assertEqual(debug[0]["when"], "vm_capacity_login_notice | length > 0")


if __name__ == "__main__":
    unittest.main()
