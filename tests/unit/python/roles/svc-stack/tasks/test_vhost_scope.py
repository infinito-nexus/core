from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

VHOST_TASKS = PROJECT_ROOT / "roles/svc-stack/tasks/proxy/vhost.yml"
DOMAIN_TASKS = PROJECT_ROOT / "roles/svc-stack/tasks/proxy/domain.yml"
SHARED = {
    "application_id": "{{ front_proxy_application_id }}",
    "domain": "{{ front_proxy_domain }}",
    "http_port": "{{ front_proxy_http_port }}",
    "proxy_service_key": "{{ front_proxy_service_key }}",
    "proxy_internal_port": "{{ front_proxy_internal_port }}",
}
INCLUDE_ROLE_KEYS = ("include_role", "ansible.builtin.include_role")


def _vhost_include() -> dict:
    return next(
        task
        for task in load_yaml_any(DOMAIN_TASKS)
        if task.get("ansible.builtin.include_tasks") == "proxy/vhost.yml"
    )


class TestVhostScope(unittest.TestCase):
    def test_the_vhost_include_binds_every_shared_name_to_the_vhost(self) -> None:
        bound = _vhost_include()["vars"]
        for name, value in SHARED.items():
            with self.subTest(name=name):
                self.assertEqual(bound.get(name), value)

    def test_no_plain_vhost_task_binds_a_shared_name_as_a_task_var(self) -> None:
        for task in load_yaml_any(VHOST_TASKS):
            if any(key in task for key in INCLUDE_ROLE_KEYS):
                continue
            with self.subTest(task=task.get("name")):
                self.assertEqual(sorted(set(task.get("vars") or {}) & set(SHARED)), [])


if __name__ == "__main__":
    unittest.main()
