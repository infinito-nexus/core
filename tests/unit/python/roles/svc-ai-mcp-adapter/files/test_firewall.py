"""Unit tests for the reusable MCP adapter's firewall layer."""

from __future__ import annotations

import importlib.util
import json
import unittest

from utils.firewall.compile import decide, mcp_policy, resolve

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/python/firewall.py"

spec = importlib.util.spec_from_file_location("adapter_firewall", MODULE_PATH)
firewall = importlib.util.module_from_spec(spec)
spec.loader.exec_module(firewall)

FIREWALL_ROLES = {
    "caller": {
        "allow": [
            "mcp(web-app-gitea/list_*):read",
            "mcp(web-app-gitea/create_issue):create",
            "mcp(web-app-gitea/delete_repo):delete",
        ],
        "ask": ["mcp(web-app-gitea/close_issue):update"],
        "deny": ["mcp(web-app-gitea/delete_repo):delete"],
    }
}


def agent_policy():
    return json.loads(json.dumps(mcp_policy(resolve(FIREWALL_ROLES, "caller"))))


class TestAgentFirewall(unittest.TestCase):
    def test_a_granted_call_returns_its_rule(self):
        self.assertEqual(
            firewall.authorize_agent_call(
                agent_policy(), "web-app-gitea", "list_issues", {"method": "GET"}
            ),
            "mcp(web-app-gitea/list_*):read",
        )

    def test_a_call_outside_the_grants_is_refused_with_the_matched_rule(self):
        for name, spec, reason in (
            (
                "delete_repo",
                {"method": "DELETE"},
                "deny by mcp(web-app-gitea/delete_repo):delete",
            ),
            (
                "close_issue",
                {"mutating": True},
                "ask by mcp(web-app-gitea/close_issue):update",
            ),
            ("list_issues", {"method": "POST"}, f"deny by {firewall.UNMATCHED_RULE}"),
            ("merge_pull", {"method": "GET"}, f"deny by {firewall.UNMATCHED_RULE}"),
        ):
            with self.subTest(name=name, spec=spec):
                with self.assertRaises(PermissionError) as error:
                    firewall.authorize_agent_call(
                        agent_policy(), "web-app-gitea", name, spec
                    )
                self.assertEqual(
                    str(error.exception), f"{firewall.DENY_FIREWALL}: {reason}"
                )

    def test_another_provider_is_not_granted_by_a_gitea_rule(self):
        with self.assertRaises(PermissionError):
            firewall.authorize_agent_call(
                agent_policy(), "web-app-gitlab", "list_issues", {"method": "GET"}
            )

    def test_the_adapter_verdict_equals_the_compiled_decision(self):
        resolved = resolve(FIREWALL_ROLES, "caller")
        for tool in ("list_issues", "create_issue", "delete_repo", "close_issue"):
            for action in ("create", "read", "update", "delete"):
                target = f"web-app-gitea/{tool}"
                with self.subTest(target=target, action=action):
                    self.assertEqual(
                        firewall.firewall_verdict(agent_policy(), target, action)[0],
                        decide(resolved, "mcp", target, action),
                    )


if __name__ == "__main__":
    unittest.main()
