from __future__ import annotations

import unittest

from tests.utils.ansible_assert import assert_task, holds, message
from utils import PROJECT_ROOT

TASKS = (
    PROJECT_ROOT / "roles" / "svc-virt-kata" / "tasks" / "utils" / "assert" / "kvm.yml"
)
TASK = assert_task(TASKS, "🛑 Refuse a host without hardware virtualization")


def _facts(exists: bool, ischr: bool) -> dict:
    return {
        "assert_kvm_device": {"stat": {"exists": exists, "ischr": ischr}},
        "assert_kvm_consumer": "web-app-proxmox",
        "inventory_hostname": "dc1",
    }


class TestAssertKvm(unittest.TestCase):
    def test_host_with_kvm_passes(self):
        self.assertTrue(holds(TASK, _facts(True, True)))

    def test_host_without_kvm_is_refused(self):
        self.assertFalse(holds(TASK, _facts(False, False)))

    def test_a_regular_file_is_no_kvm_device(self):
        self.assertFalse(holds(TASK, _facts(True, False)))

    def test_refusal_is_actionable(self):
        text = message(TASK, _facts(False, False))
        for needle in ("web-app-proxmox", "dc1", "/dev/kvm", "kvm_intel", "nested=1"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
