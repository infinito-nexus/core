"""L11: every role that can push denies writes to the protected paths, so no
agent can rewrite its own governance (firewall, routines, AGENTS.md, SOUL.md,
the compiler, the workflows). Checked through the compiler, so a role that
inherits push through an include is covered too."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, load
from utils.cache.yaml import dump_yaml_str
from utils.firewall.compile import decide, resolve

FIREWALL = AGENTS_DIR / "firewall"


def check(firewall_dir: Path) -> list[str]:
    problems: list[str] = []
    roles = load(firewall_dir / "roles.yml") or {}
    for name in roles:
        r = resolve(roles, name)
        can_push = decide(r, "app", "fork/push", "create") == "allow"
        explicit_deny = any(
            rule.kind == "app" and rule.target == "repo/protected-paths"
            for rule in r.deny
        )
        if can_push and not explicit_deny:
            problems.append(
                f"{name}: can push but has no explicit protected-paths deny"
            )
    return problems


class TestL11(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(FIREWALL), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = Path(tmp)
            (fw / "roles.yml").write_text(
                dump_yaml_str({"rogue": {"allow": ["app(fork/push):create"]}}),
                encoding="utf-8",
            )
            self.assertNotEqual(check(fw), [])


if __name__ == "__main__":
    unittest.main()
