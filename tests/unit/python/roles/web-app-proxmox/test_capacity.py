from __future__ import annotations

import importlib.util
import json
import unittest

from plugins.filter.agent_vm_capacity import agent_vm_capacity

from ._render import PROXMOX, ROLE

_SPEC = importlib.util.spec_from_file_location(
    "proxmox_capacity_filters", ROLE / "filter_plugins" / "proxmox_capacity.py"
)
_FILTERS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FILTERS)
proxmox_agent_pool = _FILTERS.proxmox_agent_pool
proxmox_agent_usage = _FILTERS.proxmox_agent_usage
proxmox_image_storages = _FILTERS.proxmox_image_storages

GIB = 1024**3
MIB = 1024**2
NODE = "pve"
POOL = "agents-example-org"
WORKSPACE_POOL = "ws-0c6f7a52-3d1e-4b8a-9f00-2a7b1c9d4e5f"


def _vm(vmid: int, pool: str | None, status: str, memhost: int, template: int = 0):
    entry = {
        "id": f"qemu/{vmid}",
        "vmid": vmid,
        "type": "qemu",
        "node": NODE,
        "name": f"vm{vmid}",
        "status": status,
        "template": template,
        "mem": memhost // 2,
        "memhost": memhost,
        "maxmem": 8 * GIB,
        "disk": 0,
        "maxdisk": 64 * GIB,
    }
    if pool:
        entry["pool"] = pool
    return entry


def _storage(storage: str, content: str, shared: int = 0, node: str = NODE):
    return {
        "id": f"storage/{node}/{storage}",
        "storage": storage,
        "type": "storage",
        "node": node,
        "status": "available",
        "shared": shared,
        "content": content,
        "plugintype": "lvmthin" if storage == "local-lvm" else "dir",
        "disk": 10 * GIB,
        "maxdisk": 100 * GIB,
    }


RESOURCES = [
    _vm(100, POOL, "running", 2 * GIB),
    _vm(101, POOL, "stopped", 0),
    _vm(9000, POOL, "stopped", 0, template=1),
    _vm(200, WORKSPACE_POOL, "running", 4 * GIB),
    _vm(300, None, "running", 4 * GIB),
    _storage("local", "iso,vztmpl,backup"),
    _storage("local-lvm", "rootdir,images"),
    _storage("vmdir", "images"),
    _storage("nfs", "images", shared=1),
    _storage("local-lvm", "rootdir,images", node="other"),
    {"id": f"node/{NODE}", "type": "node", "node": NODE, "status": "online"},
    {"id": f"/pool/{POOL}", "type": "pool", "pool": POOL},
]


def _volume(volid: str, vmid: int, size: int, used: int | None = None) -> dict:
    entry = {"volid": volid, "vmid": vmid, "size": size, "content": "images"}
    if used is None:
        return {**entry, "format": "raw"}
    return {**entry, "format": "qcow2", "used": used}


def _lv(name: str, size: int, data_percent: str) -> dict:
    return {"lv_name": name, "lv_size": str(size), "data_percent": data_percent}


LVM_THIN_VOLUMES = [
    _volume("local-lvm:vm-100-disk-0", 100, 64 * GIB),
    _volume("local-lvm:vm-100-cloudinit", 100, 4 * MIB),
    _volume("local-lvm:base-9000-disk-0", 9000, 8 * GIB),
    _volume("local-lvm:vm-200-disk-0", 200, 64 * GIB),
]
DIR_VOLUMES = [
    _volume("vmdir:101/vm-101-disk-0.qcow2", 101, 64 * GIB, used=3 * GIB),
    _volume("vmdir:300/vm-300-disk-0.qcow2", 300, 64 * GIB, used=9 * GIB),
]
THIN_REPORT = {
    "report": [
        {
            "lv": [
                _lv("data", 100 * GIB, "20.00"),
                _lv("root", 16 * GIB, ""),
                _lv("vm-100-disk-0", 64 * GIB, "6.25"),
                _lv("vm-100-cloudinit", 4 * MIB, "100.00"),
                _lv("base-9000-disk-0", 8 * GIB, "50.00"),
                _lv("vm-200-disk-0", 64 * GIB, "50.00"),
            ]
        }
    ]
}
SKIPPED = {"changed": False, "skipped": True, "skip_reason": "Conditional false"}
SKIPPED_LOOP = {**SKIPPED, "results": [], "skipped_reason": "No items in the list"}
AGENT_DISK = 4 * GIB + 4 * MIB + 3 * GIB


def _ran(payload: object) -> dict:
    return {"changed": False, "rc": 0, "stdout": json.dumps(payload), "stderr": ""}


def _volumes(*per_storage: tuple[str, list]) -> dict:
    results = [{**_ran(listed), "item": storage} for storage, listed in per_storage]
    return {"changed": False, "results": results}


def _usage(resources=None, volumes=None, thin=None) -> dict:
    return proxmox_agent_usage(
        _ran(RESOURCES) if resources is None else resources,
        _volumes(("local-lvm", LVM_THIN_VOLUMES), ("vmdir", DIR_VOLUMES))
        if volumes is None
        else volumes,
        _ran(THIN_REPORT) if thin is None else thin,
        POOL,
    )


AGENT_WORKSPACE = {
    "kind": "proxmox",
    "model_access": "gateway",
    "target": "pve-host",
    "resources": {"vcpu": 2, "memory": "8GiB", "disk": "64GiB"},
}
DOCKER_ROOT = {"size": "", "used": 0}
GUEST_STORAGE = "local-lvm"


def _shortages(
    usage: dict,
    free_memory: int,
    free_disk: int,
    pool: dict | None = None,
    workspaces: tuple = (AGENT_WORKSPACE,),
) -> list[str]:
    pool = DOCKER_ROOT if pool is None else pool
    return agent_vm_capacity(
        list(workspaces),
        "proxmox",
        "pve-host",
        1,
        PROXMOX["agents"]["warm_pool"],
        PROXMOX["agents"]["reserve"],
        free_memory,
        usage["memory"],
        [{"mount": "/", "size_available": free_disk}],
        "/var/lib/docker",
        pool["size"],
        pool["used"],
        usage["disk"],
        PROXMOX["agents"]["overhead"],
        {},
    )


def _status(total: int, used: int) -> dict:
    status = {"total": total, "used": used, "avail": total - used, "active": 1}
    results = [{**_ran({**status, "type": "lvmthin"}), "item": GUEST_STORAGE}]
    return {"changed": False, "results": results}


class TestImageStorages(unittest.TestCase):
    def test_only_the_local_image_storages_of_the_node_are_read(self):
        self.assertEqual(
            proxmox_image_storages(_ran(RESOURCES), NODE, ""), ["local-lvm", "vmdir"]
        )

    def test_the_vm_flavor_reads_only_the_guest_storage_of_the_agent_disks(self):
        self.assertEqual(
            proxmox_image_storages(_ran(RESOURCES), NODE, GUEST_STORAGE),
            [GUEST_STORAGE],
        )
        self.assertEqual(proxmox_image_storages(_ran(RESOURCES), NODE, "nfs"), [])

    def test_a_storage_id_outside_the_proxmox_format_is_left_out(self):
        planted = [*RESOURCES, _storage("x; reboot", "images")]
        self.assertEqual(
            proxmox_image_storages(_ran(planted), NODE, ""), ["local-lvm", "vmdir"]
        )
        self.assertEqual(proxmox_image_storages(_ran(planted), NODE, "x; reboot"), [])

    def test_a_node_that_does_not_run_yet_lists_no_storage(self):
        self.assertEqual(proxmox_image_storages(SKIPPED, NODE, ""), [])


class TestAgentDiskPool(unittest.TestCase):
    def test_the_vm_flavor_reads_the_guest_storage_as_a_fixed_pool(self):
        self.assertEqual(
            proxmox_agent_pool(_status(38 * GIB, 6 * GIB), GUEST_STORAGE, "64G"),
            {"size": str(38 * GIB), "used": 6 * GIB},
        )

    def test_a_first_vm_deploy_bounds_the_pool_by_the_guest_disk(self):
        for status in (SKIPPED_LOOP, {"results": [{**SKIPPED, "item": "local-lvm"}]}):
            with self.subTest(status=status):
                self.assertEqual(
                    proxmox_agent_pool(status, GUEST_STORAGE, PROXMOX["guest"]["disk"]),
                    {"size": str(64 * GIB), "used": 0},
                )

    def test_a_guest_that_does_not_answer_falls_back_to_the_guest_disk(self):
        failed = {"results": [{"rc": 255, "stdout": "", "item": GUEST_STORAGE}]}
        self.assertEqual(
            proxmox_agent_pool(failed, GUEST_STORAGE, "64G")["size"], str(64 * GIB)
        )

    def test_the_container_flavor_keeps_the_free_space_of_the_docker_root(self):
        self.assertEqual(
            proxmox_agent_pool(_status(38 * GIB, 6 * GIB), "", "64G"), DOCKER_ROOT
        )


class TestAgentUsage(unittest.TestCase):
    def test_running_agent_vms_count_the_memory_they_hold_on_the_host(self):
        self.assertEqual(_usage()["memory"], 2 * GIB)

    def test_agent_volumes_count_the_space_they_take(self):
        self.assertEqual(_usage()["disk"], AGENT_DISK)

    def test_templates_workspace_servers_and_unpooled_vms_count_for_nothing(self):
        others = [vm for vm in RESOURCES if vm.get("vmid") not in (100, 101)]
        self.assertEqual(
            _usage(resources=_ran(others)), {"memory": 0, "disk": 0}, "only own VMs"
        )

    def test_lvm_thin_volumes_without_the_thin_report_count_as_used(self):
        self.assertEqual(_usage(thin={**_ran({}), "rc": 5})["disk"], 3 * GIB)

    def test_a_guest_that_does_not_answer_counts_nothing(self):
        failed = {"changed": False, "rc": 255, "stdout": "", "stderr": "timeout"}
        self.assertEqual(
            _usage(resources=failed, volumes=SKIPPED_LOOP, thin=failed),
            {"memory": 0, "disk": 0},
        )


class TestRedeployCapacity(unittest.TestCase):
    def test_a_redeploy_counts_the_agent_vms_as_free(self):
        self.assertEqual(_shortages(_usage(), 18 * GIB, 171 * GIB), [])

    def test_negative_control_counting_them_as_used_refuses_the_same_host(self):
        found = _shortages({"memory": 0, "disk": 0}, 18 * GIB, 171 * GIB)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(found[0].startswith("free memory"), found)
        self.assertTrue(found[1].startswith("free disk"), found)

    def test_a_first_deploy_reads_nothing_and_still_runs_the_check(self):
        usage = proxmox_agent_usage(SKIPPED, SKIPPED_LOOP, SKIPPED, POOL)
        self.assertEqual(usage, {"memory": 0, "disk": 0})
        self.assertEqual(len(_shortages(usage, 18 * GIB, 171 * GIB)), 2)
        self.assertEqual(_shortages(usage, 20 * GIB, 178 * GIB), [])


class TestVmFlavorCapacity(unittest.TestCase):
    def test_a_small_guest_pool_is_refused_although_the_host_disk_is_large(self):
        pool = proxmox_agent_pool(_status(100 * GIB, 6 * GIB), GUEST_STORAGE, "64G")
        found = _shortages(_usage(), 18 * GIB, 1000 * GIB, pool)
        self.assertEqual(len(found), 1, found)
        self.assertIn("fixed storage pool", found[0])

    def test_control_a_large_guest_pool_passes(self):
        pool = proxmox_agent_pool(_status(200 * GIB, 6 * GIB), GUEST_STORAGE, "64G")
        self.assertEqual(_shortages(_usage(), 18 * GIB, 1000 * GIB, pool), [])

    def test_a_first_vm_deploy_is_bounded_by_the_guest_disk(self):
        usage = proxmox_agent_usage(SKIPPED, SKIPPED_LOOP, SKIPPED, POOL)
        small = proxmox_agent_pool(SKIPPED_LOOP, GUEST_STORAGE, "64G")
        found = _shortages(usage, 20 * GIB, 1000 * GIB, small)
        self.assertEqual(len(found), 1, found)
        self.assertIn("fixed storage pool", found[0])
        large = proxmox_agent_pool(SKIPPED_LOOP, GUEST_STORAGE, "512G")
        self.assertEqual(_shortages(usage, 20 * GIB, 1000 * GIB, large), [])

    def test_the_host_reserve_stays_outside_the_guest_pool(self):
        pool = proxmox_agent_pool(_status(38 * GIB, 6 * GIB), GUEST_STORAGE, "64G")
        usage = {"memory": 0, "disk": 0}
        self.assertEqual(_shortages(usage, 20 * GIB, 1000 * GIB, pool, ()), [])


if __name__ == "__main__":
    unittest.main()
