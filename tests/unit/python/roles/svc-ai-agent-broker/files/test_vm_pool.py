from __future__ import annotations

import importlib.util
import sys
import unittest

from . import PROJECT_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "broker_vm_pool",
    PROJECT_ROOT / "roles/svc-ai-agent-broker/files/python/vm_pool.py",
)
vm_pool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = vm_pool
_SPEC.loader.exec_module(vm_pool)

RUN = vm_pool.Task("routine_run", "run-1")
PACKAGE = vm_pool.Task("work_package", "wp-42")


def _pool() -> vm_pool.Pool:
    pool = vm_pool.Pool("prod", "broker-a", 300)
    pool.warm = {"small": ["vm-1", "vm-2"], "large": []}
    return pool


class TestTask(unittest.TestCase):
    def test_a_task_is_a_routine_run_or_a_work_package(self):
        self.assertEqual(RUN.kind, "routine_run")
        self.assertEqual(PACKAGE.kind, "work_package")
        with self.assertRaises(vm_pool.LeaseError):
            vm_pool.Task("chat", "x")
        with self.assertRaises(vm_pool.LeaseError):
            vm_pool.Task("routine_run", "")


class TestPool(unittest.TestCase):
    def test_one_vm_serves_one_task(self):
        pool = _pool()
        first = pool.assign(RUN, "small", 0)
        second = pool.assign(PACKAGE, "small", 0)
        self.assertNotEqual(first.vm, second.vm)
        with self.assertRaises(vm_pool.LeaseError):
            pool.assign(RUN, "small", 0)
        with self.assertRaises(vm_pool.LeaseError):
            pool.lease(first.vm, vm_pool.Task("routine_run", "run-2"), 0)

    def test_lease_names_instance_broker_and_expiry(self):
        lease = _pool().assign(RUN, "small", 1000)
        self.assertEqual(
            (lease.instance, lease.broker, lease.expiry), ("prod", "broker-a", 1300)
        )

    def test_empty_pool_hands_back_none_for_a_clone(self):
        self.assertIsNone(_pool().assign(RUN, "large", 0))

    def test_released_vm_is_destroyed_not_reused(self):
        pool = _pool()
        lease = pool.assign(RUN, "small", 0)
        self.assertEqual(pool.release(RUN), lease.vm)
        self.assertNotIn(lease.vm, pool.warm["small"])
        self.assertNotIn(lease.vm, pool.leases)
        with self.assertRaises(vm_pool.LeaseError):
            pool.release(RUN)

    def test_vms_without_a_live_lease_are_orphans(self):
        pool = _pool()
        live = pool.assign(RUN, "small", 0)
        found = pool.orphans(["vm-2", live.vm, "vm-stale"], 100)
        self.assertEqual(found, ["vm-stale"])
        self.assertEqual(
            pool.orphans(["vm-2", live.vm], 400), [live.vm], "expired lease kept"
        )

    def test_foreign_instance_lease_is_not_live(self):
        pool = _pool()
        pool.leases["vm-x"] = vm_pool.Lease("vm-x", RUN, "staging", "broker-b", 999)
        self.assertEqual(pool.orphans(["vm-x"], 0), ["vm-x"])

    def test_shortfall_per_size_class(self):
        self.assertEqual(
            _pool().shortfall({"small": 3, "large": 1}), {"small": 1, "large": 1}
        )
        self.assertEqual(_pool().shortfall({"small": 2}), {})


if __name__ == "__main__":
    unittest.main()
