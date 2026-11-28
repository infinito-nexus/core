from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

from tests.utils.ansible_assert import assert_task, holds
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VARIANTS, ROLE_FILE_VARS_MAIN

from ._render import COMPOSE, DOCKERFILE, PROXMOX, ROLE, render, service

_SPEC = importlib.util.spec_from_file_location(
    "proxmox_flavor_filters", ROLE / "filter_plugins" / "proxmox_flavors.py"
)
_FILTERS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FILTERS)

VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
VARIANTS = load_yaml_any(str(ROLE / ROLE_FILE_META_VARIANTS), default_if_missing=[])
CORE = load_yaml_any(str(ROLE / "tasks" / "01_access.yml"), default_if_missing=[])
GUARD = ROLE / "tasks" / "utils" / "stack" / "guard.yml"
FLAVOR = assert_task(GUARD, "🛑 Refuse a flavor the role does not ship")
COHOST = assert_task(
    GUARD,
    "🛑 Refuse a container flavor host shared with identity, gateway or vault",
)
CONTAINER_GRANTS = {
    "devices": ["/dev/kvm", "/dev/net/tun", "/dev/vhost-net", "/dev/fuse"],
    "cap_add": ["NET_ADMIN", "SYS_ADMIN"],
    "cgroup": "private",
}
PEERS = ("web-app-keycloak", "svc-ai-litellm", "web-app-openbao")
SHIPPED = ("meta", "vars", "tasks", "templates", "filter_plugins", "files")


def releases(ve: dict) -> tuple[str, str]:
    """Args:
        ve: ``services.proxmox.ve``.

    Returns:
        The release the vm flavor's ISO installs and the release the container
        flavor's pve-manager pin belongs to.
    """
    return (
        _FILTERS.proxmox_iso_release(ve["iso"]["file"]),
        _FILTERS.proxmox_package_release(ve["packages"]["pve-manager"]),
    )


def _variant_flavors() -> list[str]:
    return [row["services"]["proxmox"]["flavor"] for row in VARIANTS]


class TestFlavors(unittest.TestCase):
    def test_every_proxmox_flavor_has_its_variant(self):
        self.assertEqual(PROXMOX["flavor"], "vm")
        self.assertEqual(VARS["PROXMOX_FLAVORS"], ["vm", "container"])
        self.assertEqual(sorted(_variant_flavors()), sorted(VARS["PROXMOX_FLAVORS"]))
        for flavor in VARS["PROXMOX_FLAVORS"]:
            self.assertTrue(
                (ROLE / "tasks" / "flavors" / f"{flavor}.yml").is_file(), flavor
            )
            self.assertTrue(
                holds(
                    FLAVOR,
                    {
                        "PROXMOX_FLAVOR": flavor,
                        "PROXMOX_FLAVORS": VARS["PROXMOX_FLAVORS"],
                    },
                )
            )
        self.assertFalse(
            holds(
                FLAVOR,
                {"PROXMOX_FLAVOR": "kvm", "PROXMOX_FLAVORS": VARS["PROXMOX_FLAVORS"]},
            )
        )
        dispatch = next(
            t for t in CORE if "flavors/" in str(t.get("ansible.builtin.include_tasks"))
        )
        self.assertEqual(
            dispatch["ansible.builtin.include_tasks"],
            "flavors/{{ PROXMOX_FLAVOR }}.yml",
        )
        self.assertIn("iso", PROXMOX["ve"])
        self.assertIn("packages", PROXMOX["ve"])

    def test_negative_control_a_flavor_without_a_variant_is_caught(self):
        flavors = _variant_flavors()[:1]
        self.assertNotEqual(sorted(flavors), sorted(VARS["PROXMOX_FLAVORS"]))

    def test_both_pins_name_one_release(self):
        iso, package = releases(PROXMOX["ve"])
        self.assertEqual(iso, package)
        self.assertRegex(PROXMOX["ve"]["iso"]["sha256"], r"^[0-9a-f]{64}$")

    def test_negative_control_a_drifted_pin_is_caught(self):
        drifted = {
            **PROXMOX["ve"],
            "iso": {**PROXMOX["ve"]["iso"], "file": "proxmox-ve_9.1-1.iso"},
        }
        iso, package = releases(drifted)
        self.assertNotEqual(iso, package)


class TestContainerFlavor(unittest.TestCase):
    def test_the_container_flavor_keeps_its_grants(self):
        container = service("container")
        for key, value in CONTAINER_GRANTS.items():
            self.assertEqual(container[key], value, key)
        self.assertEqual(container["tmpfs"], ["/run", "/run/lock"])
        pins = container["build"]["args"]["PROXMOX_PACKAGES"].split()
        self.assertEqual(
            sorted(pin.split("=")[0] for pin in pins), sorted(PROXMOX["ve"]["packages"])
        )
        dockerfile = render(DOCKERFILE, "container")
        self.assertIn(
            "install -y --no-install-recommends ${PROXMOX_PACKAGES} systemd-sysv",
            dockerfile,
        )
        self.assertIn('CMD ["/sbin/init"]', dockerfile)
        vm = service("vm")
        for key in ("cap_add", "cgroup", "tmpfs"):
            self.assertNotIn(key, vm)
        self.assertEqual(vm["devices"], ["/dev/kvm"])
        vm_pins = vm["build"]["args"]["PROXMOX_PACKAGES"]
        for package in PROXMOX["ve"]["packages"]:
            self.assertNotIn(f"{package}=", vm_pins)
        self.assertNotIn("systemd-sysv", render(DOCKERFILE, "vm"))

    def test_the_container_refusal_has_no_override(self):
        for peer in PEERS:
            scope = {"PROXMOX_FLAVOR": "container", "PROXMOX_COHOSTED_PEERS": [peer]}
            self.assertFalse(holds(COHOST, scope), peer)
            self.assertFalse(
                holds(
                    COHOST, {**scope, "PROXMOX_SHARED_HOST": True, "shared_host": True}
                ),
                peer,
            )
        self.assertTrue(
            holds(COHOST, {"PROXMOX_FLAVOR": "container", "PROXMOX_COHOSTED_PEERS": []})
        )
        that = " ".join(COHOST["ansible.builtin.assert"]["that"])
        self.assertNotIn("shared", that)
        self.assertIn("proxmox_cohosted(", VARS["PROXMOX_COHOSTED_PEERS"])
        self.assertEqual(VARS["PROXMOX_EXCLUSIVE_PEERS"], list(PEERS))

    def test_no_shared_host_key_ships(self):
        shipped = tuple(f"{ROLE / folder}{os.sep}" for folder in SHIPPED)
        offenders = [
            str(Path(path).relative_to(ROLE))
            for path in sorted(iter_project_files())
            if path.startswith(shipped) and "shared_host" in read_text(path)
        ]
        self.assertEqual(offenders, [])
        self.assertNotIn("shared_host", PROXMOX)
        self.assertNotIn("shared_host", read_text(str(ROLE / "README.md")))

    def test_negative_control_an_override_clause_is_caught(self):
        that = (
            COHOST["ansible.builtin.assert"]["that"][0]
            + " or (PROXMOX_SHARED_HOST | bool)"
        )
        mutant = {"ansible.builtin.assert": {"that": [that]}}
        scope = {
            "PROXMOX_FLAVOR": "container",
            "PROXMOX_COHOSTED_PEERS": ["web-app-keycloak"],
            "PROXMOX_SHARED_HOST": True,
        }
        self.assertTrue(holds(mutant, scope))
        self.assertIn("SHARED", that)


class TestComposeTemplate(unittest.TestCase):
    def test_both_flavors_publish_only_the_ui_port(self):
        for flavor in ("vm", "container"):
            self.assertEqual(len(service(flavor)["ports"]), 1, flavor)
        self.assertIn("{% if PROXMOX_IS_VM | bool %}", COMPOSE)


if __name__ == "__main__":
    unittest.main()
