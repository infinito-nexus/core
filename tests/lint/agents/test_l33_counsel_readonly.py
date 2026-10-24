"""L33: the counsel is read-only. Its agent.yml has write_enabled false, its
firewall role grants no commit, push or write request to an instance, and its
agents/skills/i8-advocate skill names the portable advocate skill."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tests.lint.agents import AGENTS_DIR, load
from utils.firewall.compile import decide, resolve

ROLES = AGENTS_DIR / "roles"
FIREWALL = AGENTS_DIR / "firewall"
SKILLS = AGENTS_DIR / "skills"
WRITE_PROBES = (
    ("app", "fork/commit", "create"),
    ("app", "fork/push", "create"),
    ("app", "instance/write", "update"),
)


def check(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    agent = load(agents_dir / "roles" / "counsel" / "agent.yml") or {}
    if agent.get("write_enabled") is not False:
        problems.append("counsel agent.yml write_enabled is not false")
    roles = load(agents_dir / "firewall" / "roles.yml") or {}
    resolved = resolve(roles, "counsel")
    for kind, target, action in WRITE_PROBES:
        if decide(resolved, kind, target, action) == "allow":
            problems.append(f"counsel firewall allows a write: {kind}({target}):{action}")
    advocate = agents_dir / "skills" / "i8-advocate" / "SKILL.md"
    if not advocate.is_file():
        problems.append("agents/skills/i8-advocate missing")
    elif "advocate" not in advocate.read_text(encoding="utf-8"):
        problems.append("i8-advocate does not name the portable advocate skill")
    return problems


class TestL33(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp)
            (agents / "roles" / "counsel").mkdir(parents=True)
            (agents / "roles" / "counsel" / "agent.yml").write_text(
                "write_enabled: true\n", encoding="utf-8"
            )
            (agents / "firewall").mkdir()
            (agents / "firewall" / "roles.yml").write_text(
                yaml.safe_dump({"counsel": {"allow": ["app(fork/push):create"]}}),
                encoding="utf-8",
            )
            (agents / "skills").mkdir()
            self.assertNotEqual(check(agents), [])


if __name__ == "__main__":
    unittest.main()
