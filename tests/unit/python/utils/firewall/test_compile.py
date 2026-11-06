from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.firewall.compile import (
    decide,
    egress_allowlist,
    login_hosts,
    resolve,
    vm_egress_proxy,
)

PROVIDERS_DIR = PROJECT_ROOT / "agents" / "firewall" / "providers"
ROLES = {
    "contributor": {
        "allow": ["egress(github.com)", "egress(registry.example)"],
        "deny": ["egress(registry.example)"],
    }
}


def _providers() -> dict[str, dict]:
    return {path.stem: load_yaml(path) for path in sorted(PROVIDERS_DIR.glob("*.yml"))}


class TestVmEgressProxy(unittest.TestCase):
    def test_gateway_mode_admits_exactly_the_compiled_grants(self):
        resolved = resolve(ROLES, "contributor")
        policy = vm_egress_proxy(
            resolved, "gateway", login_hosts(_providers(), "claude-code")
        )
        self.assertEqual(policy["admit"], egress_allowlist(resolved))
        self.assertEqual(policy["admit"], ["github.com"])
        self.assertEqual(policy["match"], ["sni", "host"])
        self.assertEqual(policy["unmatched"], "deny")

    def test_login_mode_adds_only_the_declared_vendor_hosts(self):
        resolved = resolve(ROLES, "contributor")
        vendor = login_hosts(_providers(), "claude-code")
        self.assertIn("api.anthropic.com", vendor)
        self.assertNotIn("chatgpt.com", vendor)
        policy = vm_egress_proxy(resolved, "login", vendor)
        self.assertEqual(set(policy["admit"]), {"github.com", *vendor})

    def test_login_mode_never_readmits_a_denied_vendor_host(self):
        roles = {
            "r": {
                "allow": ["egress(github.com)"],
                "deny": ["egress(console.anthropic.com)"],
            }
        }
        resolved = resolve(roles, "r")
        self.assertEqual(decide(resolved, "egress", "console.anthropic.com"), "deny")
        policy = vm_egress_proxy(
            resolved, "login", login_hosts(_providers(), "claude-code")
        )
        self.assertNotIn("console.anthropic.com", policy["admit"])
        self.assertIn("console.anthropic.com", policy["refuse"])
        self.assertIn("api.anthropic.com", policy["admit"])

    def test_specific_deny_under_a_wildcard_allow_is_refused_first(self):
        roles = {
            "r": {
                "allow": ["egress(*.example.com)"],
                "deny": ["egress(evil.example.com)"],
            }
        }
        policy = vm_egress_proxy(resolve(roles, "r"), "gateway", [])
        self.assertEqual(policy["refuse"], ["evil.example.com"])
        self.assertEqual(policy["order"], ["refuse", "admit"])
        self.assertIn("*.example.com", policy["admit"])

    def test_deny_in_another_spelling_still_removes_the_vendor_host(self):
        for spelling in (
            "API.ANTHROPIC.COM",
            "api.anthropic.com.",
            "Api.Anthropic.Com",
        ):
            roles = {"r": {"deny": [f"egress({spelling})"]}}
            policy = vm_egress_proxy(
                resolve(roles, "r"), "login", login_hosts(_providers(), "claude-code")
            )
            self.assertNotIn("api.anthropic.com", policy["admit"], spelling)
            self.assertEqual(policy["refuse"], ["api.anthropic.com"], spelling)

    def test_deploy_variables_keep_their_case(self):
        roles = {"r": {"allow": ["egress(${INFINITO_PACKAGE_CACHE})"]}}
        self.assertEqual(
            egress_allowlist(resolve(roles, "r")), ["${INFINITO_PACKAGE_CACHE}"]
        )

    def test_user_content_apps_are_no_login_hosts(self):
        self.assertNotIn("claude.ai", login_hosts(_providers(), "claude-code"))
        self.assertNotIn("chatgpt.com", login_hosts(_providers(), "codex"))

    def test_runtime_without_a_declared_vendor_adds_nothing(self):
        self.assertEqual(login_hosts(_providers(), "hermes"), [])

    def test_vendor_hosts_follow_the_declaration(self):
        providers = {
            "acme": {"runtimes": ["pi"], "login_hosts": ["login.acme.test"]},
            "other": {"runtimes": ["codex"], "login_hosts": ["other.test"]},
        }
        self.assertEqual(login_hosts(providers, "pi"), ["login.acme.test"])


if __name__ == "__main__":
    unittest.main()
