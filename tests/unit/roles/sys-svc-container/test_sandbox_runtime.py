import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT

TEMPLATES = Path(PROJECT_ROOT) / "roles" / "sys-svc-container" / "templates"


def _ansible_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


def _shim(exists):
    return SimpleNamespace(stat=SimpleNamespace(exists=exists))


BASE = {
    "DEPLOYMENT_MODE": "swarm",
    "IS_STACK_HOST": False,
    "DOCKER_IN_CONTAINER": True,
    "DOMAIN_PRIMARY": "infinito.example",
    "KATA_SHIM_BINARY": "/usr/bin/containerd-shim-kata-v2",
    "RUNSC_SHIM_BINARY": "/usr/local/bin/runsc",
    "SANDBOX_RUNTIME": "runsc",
    "SYS_SVC_CONTAINER_DATA_ROOT": "",
    "networks": {"internet": {"dns": "192.0.2.53"}},
    "swarm": {"registry": {"host": "reg", "port": 5000}},
    "groups": {"svc-registry-cache": []},
    "group_names": ["svc-virt-kata"],
    "ansible_facts": {"os_family": "Debian"},
    "SYS_SVC_CONTAINER_DOCKER_FIREWALL_BACKEND_BY_OS_FAMILY": {"Debian": "iptables"},
    "NETWORK_DOCKER_ADDRESS_POOLS": [{"base": "10.208.0.0/12", "size": 24}],
    "SYS_DOCKER_DAEMONM_MTU": 1400,
    "sys_svc_container_kvm": _shim(False),
    "sys_svc_container_kata_shim": _shim(False),
    "sys_svc_container_runsc_shim": _shim(False),
}


class TestSandboxRuntimeRegistration(unittest.TestCase):
    def _render(self, **overrides):
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            trim_blocks=True,
            lstrip_blocks=False,
            undefined=StrictUndefined,
            autoescape=select_autoescape(),
        )
        env.filters["bool"] = _ansible_bool
        raw = env.get_template("daemon.json.j2").render({**BASE, **overrides})
        return json.loads(raw)

    def test_absent_shim_is_never_registered(self):
        parsed = self._render()
        self.assertNotIn("runtimes", parsed)
        self.assertNotIn("default-runtime", parsed)

    def test_swarm_worker_defaults_to_the_installed_sandbox_runtime(self):
        parsed = self._render(sys_svc_container_runsc_shim=_shim(True))
        self.assertEqual(sorted(parsed["runtimes"]), ["runsc"])
        self.assertEqual(parsed["default-runtime"], "runsc")

    def test_stack_host_keeps_the_shared_kernel(self):
        parsed = self._render(
            IS_STACK_HOST=True, sys_svc_container_runsc_shim=_shim(True)
        )
        self.assertIn("runsc", parsed["runtimes"])
        self.assertNotIn("default-runtime", parsed)

    def test_compose_mode_never_sets_a_default_runtime(self):
        parsed = self._render(
            DEPLOYMENT_MODE="compose", sys_svc_container_runsc_shim=_shim(True)
        )
        self.assertIn("runsc", parsed["runtimes"])
        self.assertNotIn("default-runtime", parsed)

    def test_kata_wins_over_runsc_when_hardware_virtualization_is_present(self):
        parsed = self._render(
            DOCKER_IN_CONTAINER=False,
            SANDBOX_RUNTIME="kata",
            sys_svc_container_kvm=_shim(True),
            sys_svc_container_kata_shim=_shim(True),
            sys_svc_container_runsc_shim=_shim(True),
        )
        self.assertEqual(sorted(parsed["runtimes"]), ["kata", "runsc"])
        self.assertEqual(parsed["default-runtime"], "kata")

    def test_registration_follows_the_probe_not_the_inventory_group(self):
        parsed = self._render(
            group_names=["web-app-hermes"], sys_svc_container_runsc_shim=_shim(True)
        )
        self.assertEqual(sorted(parsed["runtimes"]), ["runsc"])
        self.assertEqual(parsed["default-runtime"], "runsc")

    def test_a_default_runtime_is_always_a_registered_one(self):
        for kata, runsc in ((False, False), (False, True), (True, True)):
            with self.subTest(kata=kata, runsc=runsc):
                parsed = self._render(
                    DOCKER_IN_CONTAINER=False,
                    sys_svc_container_kvm=_shim(kata),
                    sys_svc_container_kata_shim=_shim(kata),
                    sys_svc_container_runsc_shim=_shim(runsc),
                    SANDBOX_RUNTIME="kata" if kata else "runsc",
                )
                if "default-runtime" in parsed:
                    self.assertIn(parsed["default-runtime"], parsed["runtimes"])


class TestDaemonStorageDriver(unittest.TestCase):
    def _render(self, **overrides):
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            trim_blocks=True,
            lstrip_blocks=False,
            undefined=StrictUndefined,
            autoescape=select_autoescape(),
        )
        env.filters["bool"] = _ansible_bool
        raw = env.get_template("daemon.json.j2").render({**BASE, **overrides})
        return json.loads(raw)

    def test_docker_in_docker_overrides_the_storage_driver(self):
        self.assertEqual(self._render()["storage-driver"], "fuse-overlayfs")

    def test_a_bare_host_keeps_the_native_storage_driver(self):
        self.assertNotIn("storage-driver", self._render(DOCKER_IN_CONTAINER=False))


if __name__ == "__main__":
    unittest.main()
