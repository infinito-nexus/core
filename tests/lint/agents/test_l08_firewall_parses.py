"""L08: every firewall rule parses; every account provider is built in or
declared under agents/firewall/providers/; every ${VAR} names a variable
listed in agents/firewall/variables.yml; every vendor ``login_hosts`` entry is
an exact host name, never a wildcard and never a host that serves user
content."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, load
from utils.cache.yaml import dump_yaml_str
from utils.firewall.compile import decide, resolve
from utils.firewall.parse import BUILTIN_PROVIDERS, parse_rule

FIREWALL = AGENTS_DIR / "firewall"
EXACT_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")
USER_CONTENT_HOSTS = frozenset(
    {"claude.ai", "chatgpt.com", "gemini.google.com", "copilot.microsoft.com"}
)


def login_host_problems(firewall_dir: Path) -> list[str]:
    """Return every ``login_hosts`` entry that is not an exact, non user-content
    host name.

    Args:
        firewall_dir: the agents/firewall directory.
    """
    problems: list[str] = []
    for path in sorted((firewall_dir / "providers").glob("*.yml")):
        for host in (load(path) or {}).get("login_hosts") or []:
            if not EXACT_HOST.match(str(host)):
                problems.append(
                    f"{path.name}: login host {host!r} is not an exact host"
                )
            elif host in USER_CONTENT_HOSTS:
                problems.append(f"{path.name}: login host {host!r} serves user content")
    return problems


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
        if rule.kind == "egress" and f"({rule.target})" not in raw:
            problems.append(f"rule {raw!r}: write the target as {rule.target!r}")
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

    def test_real_login_hosts_pass(self):
        self.assertEqual(login_host_problems(FIREWALL), [])

    def test_wildcard_and_user_content_login_hosts_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = Path(tmp)
            (fw / "providers").mkdir()
            (fw / "providers" / "vendor.yml").write_text(
                dump_yaml_str(
                    {"login_hosts": ["*.example.com", "claude.ai", "ok.example.com"]}
                ),
                encoding="utf-8",
            )
            problems = login_host_problems(fw)
        self.assertEqual(len(problems), 2)
        self.assertIn("not an exact host", problems[0])
        self.assertIn("serves user content", problems[1])

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

    def test_a_declared_provider_is_usable_in_an_account_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = Path(tmp)
            (fw / "providers").mkdir(parents=True)
            (fw / "providers" / "codeberg.yml").write_text(
                dump_yaml_str({"base_url": "https://codeberg.org", "api": "gitea"}),
                encoding="utf-8",
            )
            (fw / "variables.yml").write_text("{}\n", encoding="utf-8")
            roles = {
                "r": {
                    "allow": [
                        "account(codeberg/maintainer):crud",
                        "account(github/maintainer):read",
                    ]
                }
            }
            (fw / "roles.yml").write_text(dump_yaml_str(roles), encoding="utf-8")
            self.assertEqual(check(fw), [])
            resolved = resolve(roles, "r")
            self.assertEqual(
                decide(resolved, "account", "codeberg/maintainer", "create"), "allow"
            )
            roles["r"]["allow"].append("account(bitbucket/maintainer):read")
            (fw / "roles.yml").write_text(dump_yaml_str(roles), encoding="utf-8")
            self.assertEqual(
                check(fw),
                [
                    (
                        "rule 'account(bitbucket/maintainer):read': provider "
                        "'bitbucket' not built in or declared"
                    )
                ],
            )

    def test_non_normalised_egress_spellings_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw = Path(tmp)
            (fw / "providers").mkdir(parents=True)
            (fw / "variables.yml").write_text("{}\n", encoding="utf-8")
            (fw / "roles.yml").write_text(
                dump_yaml_str(
                    {
                        "r": {
                            "allow": ["egress(ok.example.com)"],
                            "deny": [
                                "egress(API.ANTHROPIC.COM)",
                                "egress(api.anthropic.com.)",
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            problems = check(fw)
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(all("'api.anthropic.com'" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
