from __future__ import annotations

import unittest

from tests.utils.ansible_assert import assert_task, holds, message
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.packages.registry import build_registry
from utils.packages.schema import DISTRO_FAMILY
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_README,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "svc-virt-incus"
TASKS = ROLE / "tasks" / "00_core.yml"
TASK_LIST = load_yaml_any(str(TASKS), default_if_missing=[])
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES), default_if_missing={})
README = read_text(str(ROLE / ROLE_FILE_README))
DRIVER = assert_task(TASKS, "🛑 Refuse a storage driver without copy-on-write clones")


def _task_with(text: str) -> dict:
    for task in TASK_LIST:
        if text in str(task):
            return task
    raise AssertionError(f"no task mentions {text}")


class TestIncusHost(unittest.TestCase):
    def test_kvm_is_required(self):
        task = _task_with("svc-virt-kata/tasks/utils/assert/kvm.yml")
        self.assertEqual(task["vars"]["assert_kvm_consumer"], "{{ application_id }}")

    def test_copy_on_write_drivers_pass(self):
        for driver in ("btrfs", "zfs", "lvm"):
            scope = {
                "INCUS_STORAGE_POOL": {"driver": driver},
                "INCUS_COW_DRIVERS": VARS["INCUS_COW_DRIVERS"],
            }
            self.assertTrue(holds(DRIVER, scope), driver)

    def test_dir_driver_is_refused(self):
        scope = {
            "INCUS_STORAGE_POOL": {"driver": "dir"},
            "INCUS_COW_DRIVERS": VARS["INCUS_COW_DRIVERS"],
        }
        self.assertFalse(holds(DRIVER, scope))
        self.assertIn("dir driver", message(DRIVER, scope))

    def test_default_pool_is_copy_on_write(self):
        self.assertIn(
            SERVICES["incus"]["storage_pool"]["driver"], VARS["INCUS_COW_DRIVERS"]
        )

    def test_project_blocks_privileged_instances_and_host_paths(self):
        config = VARS["INCUS_PROJECT_CONFIG"]
        for key, value in (
            ("restricted", "true"),
            ("restricted.containers.privilege", "unprivileged"),
            ("restricted.devices.disk", "managed"),
            ("restricted.virtual-machines.lowlevel", "block"),
        ):
            self.assertEqual(config[key], value, key)

    def test_project_carries_limits(self):
        config = VARS["INCUS_PROJECT_CONFIG"]
        self.assertIn("INCUS_MAX_RUNNING", config["limits.instances"])
        self.assertIn("warm_pool", config["limits.instances"])
        self.assertEqual(config["limits.disk"], "{{ INCUS_STORAGE_POOL.size }}")

    def test_existing_project_is_reconciled_not_only_created(self):
        create = _task_with("incus project create")
        self.assertNotIn("--config", str(create["ansible.builtin.command"]))
        reconcile = _task_with("incus project set")
        self.assertEqual(
            reconcile["loop"], "{{ svc_virt_incus_project_config.results }}"
        )
        self.assertEqual(
            reconcile["when"], "(item.stdout | trim) != (item.item.value | string)"
        )
        read = _task_with("incus project get")
        self.assertEqual(read["loop"], "{{ INCUS_PROJECT_CONFIG | dict2items }}")

    def test_preseed_bridge_has_no_nat_and_no_ipv6(self):
        bridge = VARS["INCUS_PRESEED"]["networks"][0]
        self.assertEqual(bridge["type"], "bridge")
        self.assertEqual(bridge["config"]["ipv4.nat"], "false")
        self.assertEqual(bridge["config"]["ipv6.address"], "none")
        init = _task_with("incus admin init --preseed")
        self.assertEqual(
            init["ansible.builtin.command"]["stdin"],
            "{{ INCUS_PRESEED | to_nice_yaml }}",
        )
        self.assertIs(init["changed_when"], False)

    def test_preseed_change_is_reported_from_a_real_diff(self):
        names = [task.get("name", "") for task in TASK_LIST]
        report = TASK_LIST[
            names.index("🔍 Report whether the preseed changed the Incus configuration")
        ]
        self.assertEqual(
            report["changed_when"],
            "svc_virt_incus_after.stdout != svc_virt_incus_before.stdout",
        )

    def test_capacity_counts_the_pool_and_the_running_vms(self):
        task = _task_with("svc-ai-agent-broker/tasks/utils/vm/capacity.yml")
        self.assertEqual(
            task["vars"]["vm_capacity_pool_size"], "{{ INCUS_STORAGE_POOL.size }}"
        )
        running = task["vars"]["vm_capacity_running_memory"]
        self.assertIn("selectattr('project', 'equalto', INCUS_PROJECT)", running)
        self.assertIn("state.memory.usage", running)
        self.assertEqual(task["vars"]["vm_capacity_own_disk"], 0)

    def test_platforms_match_the_distribution_check(self):
        meta = load_yaml_any(str(ROLE / ROLE_FILE_META_MAIN), default_if_missing={})
        galaxy = {p["name"] for p in meta["galaxy_info"]["platforms"]}
        family_of = {
            "ArchLinux": "Archlinux",
            "Debian": "Debian",
            "Ubuntu": "Debian",
            "EL": "RedHat",
            "Fedora": "RedHat",
        }
        families = {family_of[name] for name in galaxy}
        self.assertEqual(families, set(VARS["INCUS_OS_FAMILIES"]))
        incus = build_registry(PROJECT_ROOT)["incus"]
        self.assertEqual(
            {DISTRO_FAMILY.get(key, key) for key in incus.mapping},
            set(VARS["INCUS_OS_FAMILIES"]),
        )

    def test_readme_names_the_broker_channel_and_secure_boot(self):
        self.assertIn("vsock", README)
        self.assertIn("`security.secureboot`", README)
        self.assertIn("cloud-init", README)


if __name__ == "__main__":
    unittest.main()
