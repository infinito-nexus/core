from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from ._render import PROXMOX, ROLE

README = read_text(str(ROLE / "README.md"))
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})


def _section(title: str) -> str:
    match = re.search(
        rf"^#+ {re.escape(title)}\n(.*?)(?=^#+ |\Z)", README, re.MULTILINE | re.DOTALL
    )
    return match.group(1) if match else ""


def pool_findings(readme: str) -> list[str]:
    """Args:
        readme: README text.

    Returns:
        Every 110 topic the README leaves out.
    """
    needles = {
        "flavors": ("`vm`", "`container`", "services.proxmox.flavor"),
        "pins": (
            "services.proxmox.ve.iso",
            "services.proxmox.ve.packages",
            "same Proxmox VE release",
        ),
        "privilege models": ("non-root UID", "`no-new-privileges`", "root on the host"),
        "dedicated host": ("dedicated host", "no override"),
        "guest channel": ("Guest channel", "127.0.0.1", "published on no host address"),
        "image build": (
            "prepare-iso --fetch-from iso",
            'reboot-mode = "power-off"',
            "SHA-256",
        ),
        "first boot": (
            "fw_cfg",
            "machine id",
            "node certificate",
            "root password hash",
        ),
        "nested": ("`nested`", "`kvm: 0`", "platform/data/provision/proxmox-<host>"),
        "pools and tokens": (
            "`ws-<id>`",
            "`ws-<id>@pve!provision`",
            "tenant/data/ws-<id>-provision/proxmox",
        ),
        "api only": ("no snippet", "`source_file`", "`idmap`"),
    }
    findings = [
        f"{topic}: {needle}"
        for topic, items in needles.items()
        for needle in items
        if needle not in readme
    ]
    for role, privileges in VARS["PROXMOX_WORKSPACE_ROLES"].items():
        line = re.search(rf"^- `{role}`[^:]*: (.+)$", readme, re.MULTILINE)
        listed = (
            set(re.findall(r"`([A-Za-z]+\.[A-Za-z.]+)`", line.group(1)))
            if line
            else set()
        )
        if listed != set(privileges):
            findings.append(f"{role} lists {sorted(listed)}")
    return findings


def template_findings(readme: str) -> list[str]:
    """Args:
        readme: README text.

    Returns:
        Every 116 topic the README leaves out.
    """
    templates = PROXMOX["workspaces"]["templates"]
    needles = (
        "services.proxmox.workspaces.image",
        "services.proxmox.workspaces.templates.kvm",
        "services.proxmox.workspaces.templates.emulated",
        f"default `{templates['kvm']}`",
        f"default `{templates['emulated']}`",
        "`kvm` 0 and CPU type `qemu64`",
        "full clone",
        "clone-only right",
        "shared with the default catalog",
    )
    return [needle for needle in needles if needle not in readme]


class TestReadme(unittest.TestCase):
    def test_the_readme_names_the_workspace_pools(self):
        self.assertEqual(pool_findings(README), [])
        self.assertIn("InfinitoTemplateClone", _section("Workspace pools and tokens"))

    def test_negative_control_a_privilege_missing_from_the_readme_is_caught(self):
        mutant = README.replace("`VM.PowerMgmt`", "`VM.Console`", 1)
        self.assertNotEqual(mutant, README)
        self.assertNotEqual(pool_findings(mutant), [])

    def test_the_readme_names_the_workspace_templates(self):
        self.assertEqual(template_findings(README), [])

    def test_negative_control_a_template_section_without_the_ids_is_caught(self):
        mutant = README.replace("default `9001`", "default id")
        self.assertNotEqual(template_findings(mutant), [])


if __name__ == "__main__":
    unittest.main()
