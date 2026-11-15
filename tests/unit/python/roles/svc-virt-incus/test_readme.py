from __future__ import annotations

import unittest

from utils.cache.files import read_text

from ._incus import ROLE

README = read_text(str(ROLE / "README.md"))
TOPICS = {
    "listener": (
        "services.incus.api.enabled",
        "`core.https_address`",
        "services.incus.api.listen",
    ),
    "firewall sources": (
        "services.incus.api.allowed_sources",
        "An empty list admits no one",
        "platform/data/provision/incus-<host>",
    ),
    "join tokens": ("`core.remote_token_expiry`", "`1h`"),
    "projects": (
        "`ws-<id>`",
        "services.incus.workspaces.limits",
        "services.incus.workspaces.instance",
    ),
    "certificates": (
        "--restricted --projects ws-<id>",
        "tenant/data/ws-<id>-provision/incus",
        "no join token",
    ),
    "vm only": ("Virtual machines only", "`limits.containers` 0"),
    "routed subnet": (
        "services.incus.workspaces.subnet.ipv4",
        "services.incus.workspaces.slice",
        "`ipv4.nat` and `ipv6.nat` false",
        "no NAT rule",
        "`security.ipv6_filtering`",
    ),
    "isolation": ("between two workspace bridges",),
}


def readme_findings(readme: str) -> list[str]:
    """Args:
        readme: README text.

    Returns:
        Every 109 topic the README leaves out.
    """
    return [
        f"{topic}: {needle}"
        for topic, needles in TOPICS.items()
        for needle in needles
        if needle not in readme
    ]


class TestReadme(unittest.TestCase):
    def test_the_readme_names_the_workspace_projects(self):
        self.assertEqual(readme_findings(README), [])

    def test_negative_control_a_readme_without_the_vm_rule_is_caught(self):
        mutant = README.replace("`limits.containers` 0", "a container limit")
        self.assertNotEqual(mutant, README)
        self.assertEqual(readme_findings(mutant), ["vm only: `limits.containers` 0"])


if __name__ == "__main__":
    unittest.main()
