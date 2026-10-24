"""L09: every agent role binds at least one firewall role; every firewall role
it binds exists; every baseline role of the design is shipped."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, ROLES_DIR, load, role_names

BASELINE = (
    "workspace",
    "forge-reader",
    "package-consumer",
    "interactive",
    "autonomous-contributor",
    "maintainer",
    "designer",
    "reviewer",
    "planner",
    "coordinator",
    "operator",
    "tester",
    "documenter",
    "translator",
    "release",
    "security",
    "hacker",
    "counsel",
    "support",
)


def check(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    firewall = load(agents_dir / "firewall" / "roles.yml") or {}
    defined = set(firewall)
    problems.extend(
        f"baseline firewall role '{role}' missing from roles.yml"
        for role in BASELINE
        if role not in defined
    )
    for name, body in firewall.items():
        problems.extend(
            f"{name}: includes '{included}' which is not defined"
            for included in (body or {}).get("includes") or []
            if included not in defined
        )
    for role in role_names(agents_dir / "roles"):
        bound = (load(agents_dir / "roles" / role / "agent.yml") or {}).get(
            "firewall_roles"
        ) or []
        if not bound:
            problems.append(f"{role}: binds no firewall role")
        problems.extend(
            f"{role}: firewall role '{fw_role}' not defined"
            for fw_role in bound
            if fw_role not in defined
        )
    return problems


class TestL09(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp)
            (agents / "firewall").mkdir(parents=True)
            (agents / "firewall" / "roles.yml").write_text(
                "workspace: {}\n", encoding="utf-8"
            )
            (agents / "roles" / "ghost").mkdir(parents=True)
            (agents / "roles" / "ghost" / "agent.yml").write_text(
                "firewall_roles: [nonexistent]\n", encoding="utf-8"
            )
            self.assertNotEqual(check(agents), [])

    def test_real_roles_present(self):
        self.assertTrue(role_names(ROLES_DIR))


if __name__ == "__main__":
    unittest.main()
