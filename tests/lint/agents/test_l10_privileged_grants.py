"""L10: an app grant that maps to a privileged resource (admin, settings,
secrets, root) is flagged unless it is a deny or an ask, never a plain
allow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, load
from utils.cache.yaml import dump_yaml_str
from utils.firewall.parse import parse_rule

PRIVILEGED = ("admin", "settings", "secrets", "root")
FIREWALL = AGENTS_DIR / "firewall"


def check(firewall_dir: Path) -> list[str]:
    problems: list[str] = []
    roles = load(firewall_dir / "roles.yml") or {}
    for name, role in roles.items():
        for raw in role.get("allow") or []:
            rule = parse_rule(raw)
            if rule.kind == "app" and any(p in rule.target for p in PRIVILEGED):
                problems.append(f"{name}: privileged app grant allowed outright: {raw}")
    return problems


class TestL10(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(FIREWALL), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = Path(tmp)
            (fw / "roles.yml").write_text(
                dump_yaml_str({"bad": {"allow": ["app(github/admin-settings):crud"]}}),
                encoding="utf-8",
            )
            self.assertNotEqual(check(fw), [])


if __name__ == "__main__":
    unittest.main()
