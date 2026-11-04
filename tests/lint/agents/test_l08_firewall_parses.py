"""L08: every firewall rule parses; every account provider is built in or
declared under agents/firewall/providers/; every ${VAR} names a variable
listed in agents/firewall/variables.yml."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, load
from utils.cache.yaml import dump_yaml_str
from utils.firewall.parse import BUILTIN_PROVIDERS, parse_rule

FIREWALL = AGENTS_DIR / "firewall"


def _rules(roles: dict) -> list[str]:
    out: list[str] = []
    for role in (roles or {}).values():
        for bucket in ("allow", "ask", "deny"):
            out.extend(role.get(bucket) or [])
    return out


def check(firewall_dir: Path) -> list[str]:
    problems: list[str] = []
    roles = load(firewall_dir / "roles.yml") or {}
    known_vars = set(load(firewall_dir / "variables.yml") or {})
    declared = {p.stem for p in (firewall_dir / "providers").glob("*.yml")}
    providers = set(BUILTIN_PROVIDERS) | declared
    for raw in _rules(roles):
        try:
            rule = parse_rule(raw)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if rule.kind == "account":
            provider = rule.target.split("/")[0]
            if provider not in providers:
                problems.append(
                    f"rule {raw!r}: provider '{provider}' not built in or declared"
                )
        problems.extend(
            f"rule {raw!r}: unknown deploy variable ${{{var}}}"
            for var in rule.variables
            if var not in known_vars
        )
    return problems


class TestL08(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(FIREWALL), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = Path(tmp)
            (fw / "providers").mkdir(parents=True)
            (fw / "variables.yml").write_text("{}\n", encoding="utf-8")
            (fw / "roles.yml").write_text(
                dump_yaml_str(
                    {
                        "bad": {
                            "allow": [
                                "wizard(x):read",
                                "account(bitbucket/x):read",
                                "egress(${NOPE})",
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(check(fw), [])


if __name__ == "__main__":
    unittest.main()
