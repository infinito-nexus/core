from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from agents.routines.debug import ci as debug_ci
from tests.lint.agents.test_l09_firewall_roles_exist import BASELINE
from utils import PROJECT_ROOT
from utils.agents.accounts import default_account
from utils.agents.pre_push import bound
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.firewall.compile import (
    MISCONFIGURATION,
    SETTINGS_KIND,
    VERDICTS,
    WRITE_GATE_SCENARIOS,
    Resolved,
    account_grants,
    at_step,
    decide,
    decide_intersection,
    egress_allowlist,
    expand,
    managed_settings,
    narrow,
    resolve,
    write_gate,
)
from utils.firewall.egress import (
    account_hosts,
    login_hosts,
    remote_egress,
    vm_egress_proxy,
)

PROVIDERS_DIR = PROJECT_ROOT / "agents" / "firewall" / "providers"
FIREWALL_ROLES = PROJECT_ROOT / "agents" / "firewall" / "roles.yml"
AGENT_ROLES = PROJECT_ROOT / "agents" / "roles"
FIREWALL_VARIABLES = PROJECT_ROOT / "agents" / "firewall" / "variables.yml"
SETTINGS = PROJECT_ROOT / ".claude" / "settings.json"
_ALL_PASSED = dict.fromkeys(WRITE_GATE_SCENARIOS, True)
ROLES = {
    "contributor": {
        "allow": ["egress(github.com)", "egress(registry.example)"],
        "deny": ["egress(registry.example)"],
    }
}
PLATFORM = {
    "model_gateway": "litellm.infinito.test",
    "mcp_adapter": "MCP.infinito.test.",
    "forks": ["gitea.infinito.test"],
    "resolver": "10.0.0.53",
}
PLATFORM_HOSTS = {"mcp.infinito.test", "gitea.infinito.test"}


def _providers() -> dict[str, dict]:
    return {path.stem: load_yaml(path) for path in sorted(PROVIDERS_DIR.glob("*.yml"))}


class TestVmEgressProxy(unittest.TestCase):
    def test_gateway_mode_admits_the_grants_the_gateway_the_adapter_and_the_fork(
        self,
    ):
        resolved = resolve(ROLES, "contributor")
        policy = vm_egress_proxy(
            resolved, "gateway", login_hosts(_providers(), "claude-code"), PLATFORM
        )
        self.assertEqual(
            set(policy["admit"]),
            {*egress_allowlist(resolved), *PLATFORM_HOSTS, "litellm.infinito.test"},
        )
        self.assertNotIn("api.anthropic.com", policy["admit"])
        self.assertEqual(policy["match"], ["sni", "host"])
        self.assertEqual(policy["unmatched"], "deny")
        self.assertEqual(policy["resolver"], "10.0.0.53")

    def test_login_mode_adds_only_the_declared_vendor_hosts(self):
        resolved = resolve(ROLES, "contributor")
        vendor = login_hosts(_providers(), "claude-code")
        self.assertIn("api.anthropic.com", vendor)
        self.assertNotIn("chatgpt.com", vendor)
        policy = vm_egress_proxy(resolved, "login", vendor, PLATFORM)
        self.assertEqual(set(policy["admit"]), {"github.com", *vendor, *PLATFORM_HOSTS})

    def test_a_deny_rule_removes_a_platform_host(self):
        roles = {"r": {"deny": ["egress(gitea.infinito.test)"]}}
        policy = vm_egress_proxy(resolve(roles, "r"), "gateway", [], PLATFORM)
        self.assertNotIn("gitea.infinito.test", policy["admit"])
        self.assertIn("gitea.infinito.test", policy["refuse"])

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
            resolved, "login", login_hosts(_providers(), "claude-code"), PLATFORM
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
        policy = vm_egress_proxy(resolve(roles, "r"), "gateway", [], PLATFORM)
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
                resolve(roles, "r"),
                "login",
                login_hosts(_providers(), "claude-code"),
                PLATFORM,
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


class TestPrecedence(unittest.TestCase):
    ROLES: ClassVar[dict] = {
        "r": {
            "allow": ["app(forge/issue):crud", "app(forge/tag):create"],
            "ask": ["app(forge/issue):delete", "app(forge/tag):create"],
            "deny": ["app(forge/issue):delete"],
        }
    }

    def test_deny_beats_ask_beats_allow(self):
        resolved = resolve(self.ROLES, "r")
        self.assertEqual(decide(resolved, "app", "forge/issue", "delete"), "deny")
        self.assertEqual(decide(resolved, "app", "forge/tag", "create"), "ask")
        self.assertEqual(decide(resolved, "app", "forge/issue", "read"), "allow")

    def test_an_unmatched_request_is_denied(self):
        resolved = resolve(self.ROLES, "r")
        self.assertEqual(decide(resolved, "app", "forge/wiki", "read"), "deny")
        self.assertEqual(decide(resolved, "egress", "example.org"), "deny")
        self.assertEqual(decide(resolve({}, "missing"), "app", "x/y", "read"), "deny")


def deploy_variables() -> dict[str, str]:
    """Return a value for every variable agents/firewall/variables.yml lists:
    the lane's bind address and port, and ``<name>.test`` for the rest."""
    values = {
        name: f"{name.lower().replace('_', '-')}.test"
        for name in load_yaml(FIREWALL_VARIABLES)
    }
    values.update(
        {"INFINITO_BIND_IP": "127.0.0.1", "INFINITO_TOOLS_LIBRETRANSLATE_PORT": "5555"}
    )
    return values


class TestExpand(unittest.TestCase):
    VARIABLES: ClassVar[dict] = deploy_variables()

    def test_the_translation_lane_address_is_granted_by_its_variables(self):
        translator = expand(
            resolve(load_yaml(FIREWALL_ROLES), "translator"), self.VARIABLES
        )
        self.assertEqual(decide(translator, "egress", "127.0.0.1:5555"), "allow")
        self.assertEqual(decide(translator, "egress", "127.0.0.1:5556"), "deny")
        self.assertIn("127.0.0.1:5555", egress_allowlist(translator))

    def test_a_variable_the_deploy_lacks_is_refused(self):
        roles = {"r": {"allow": ["egress(${INFINITO_BIND_IP}:${UNSET_PORT})"]}}
        with self.assertRaises(KeyError):
            expand(resolve(roles, "r"), self.VARIABLES)

    def test_a_rule_without_variables_is_kept(self):
        roles = {"r": {"allow": ["app(fork/push):create"]}}
        resolved = resolve(roles, "r")
        self.assertEqual(expand(resolved, {}), resolved)


class TestWriteGate(unittest.TestCase):
    ROLES: ClassVar[dict] = {
        "r": {
            "allow": [
                "app(fork/push):create",
                "app(github/issue-comment):create+read",
                "app(workspace/worktree):crud",
                "mcp(openproject/work_packages):crud",
                "egress(github.com)",
            ],
            "ask": ["app(github/issue):delete"],
            "deny": ["app(upstream/push):create"],
        }
    }

    def _gated(self, write_enabled: bool, scenarios: dict) -> Resolved:
        return write_gate(
            resolve(self.ROLES, "r"),
            write_enabled=write_enabled,
            scenarios_passed=scenarios,
        )

    def _writes(self, resolved: Resolved) -> list[tuple]:
        return [
            (kind, target, action)
            for kind, target, action in (
                ("app", "fork/push", "create"),
                ("app", "github/issue-comment", "create"),
                ("mcp", "openproject/work_packages", "update"),
                ("app", "github/issue", "delete"),
            )
            if decide(resolved, kind, target, action) != "deny"
        ]

    def test_write_disabled_emits_no_write_grant(self):
        gated = self._gated(False, _ALL_PASSED)
        self.assertEqual(self._writes(gated), [])
        self.assertEqual(decide(gated, "app", "github/issue-comment", "read"), "allow")
        self.assertEqual(decide(gated, "app", "workspace/worktree", "update"), "allow")
        self.assertEqual(decide(gated, "egress", "github.com"), "allow")
        self.assertEqual(gated.deny, resolve(self.ROLES, "r").deny)

    def test_a_failed_gate_scenario_emits_no_write_grant(self):
        for failed in WRITE_GATE_SCENARIOS:
            with self.subTest(failed=failed):
                gated = self._gated(True, {**_ALL_PASSED, failed: False})
                self.assertEqual(self._writes(gated), [])

    def test_a_missing_scenario_result_emits_no_write_grant(self):
        gated = self._gated(True, {"deny": True})
        self.assertEqual(self._writes(gated), [])

    def test_write_enabled_with_every_scenario_passed_keeps_the_grants(self):
        gated = self._gated(True, _ALL_PASSED)
        self.assertEqual(len(self._writes(gated)), 4)


class TestIntersection(unittest.TestCase):
    PROFILE: ClassVar[dict] = {
        "p": {
            "allow": [
                "app(web-app-nextcloud/files):crud",
                "app(web-app-gitea/repos):read",
                "mcp(gitea/issues):read",
            ]
        }
    }
    OWNER: ClassVar[dict] = {
        "o": {
            "allow": ["app(web-app-nextcloud/files):crud", "mcp(gitea/issues):read"],
            "ask": ["app(web-app-nextcloud/files):delete"],
        }
    }

    def _verdict(self, kind, target, action):
        return decide_intersection(
            resolve(self.PROFILE, "p"), resolve(self.OWNER, "o"), kind, target, action
        )

    def test_a_right_both_hold_is_granted(self):
        self.assertEqual(
            self._verdict("app", "web-app-nextcloud/files", "read"), "allow"
        )
        self.assertEqual(self._verdict("mcp", "gitea/issues", "read"), "allow")

    def test_a_right_the_owner_lacks_is_denied(self):
        self.assertEqual(self._verdict("app", "web-app-gitea/repos", "read"), "deny")

    def test_a_right_the_profile_lacks_is_denied(self):
        self.assertEqual(self._verdict("mcp", "gitea/issues", "create"), "deny")

    def test_the_stricter_verdict_wins(self):
        self.assertEqual(
            self._verdict("app", "web-app-nextcloud/files", "delete"), "ask"
        )


def _bindings() -> dict[str, list[str]]:
    return {
        path.parent.name: load_yaml(path)["firewall_roles"]
        for path in sorted(AGENT_ROLES.glob("*/agent.yml"))
    }


def _unaccounted_egress(
    roles: dict, bindings: dict[str, list[str]]
) -> dict[str, list[str]]:
    unaccounted = {}
    for agent, names in bindings.items():
        reached = set(remote_egress(bound(roles, names)))
        granted = set(account_hosts(account_grants(roles, names), {}))
        if reached != granted:
            unaccounted[agent] = sorted(reached ^ granted)
    return unaccounted


class TestRemoteEgress(unittest.TestCase):
    def test_every_agent_reaches_exactly_its_account_hosts(self):
        bindings = _bindings()
        self.assertIn("planner", bindings)
        self.assertEqual(_unaccounted_egress(load_yaml(FIREWALL_ROLES), bindings), {})

    def test_a_remote_host_without_an_account_grant_is_caught(self):
        roles = {"reader": {"allow": ["egress(github.com)", "egress(api.github.com)"]}}
        self.assertEqual(
            _unaccounted_egress(roles, {"agent": ["reader"]}),
            {"agent": ["api.github.com", "github.com"]},
        )

    def test_a_provider_on_a_remote_instance_adds_its_exact_host(self):
        self.assertEqual(
            account_hosts(
                ["gitea/maintainer", "gitlab/maintainer"],
                {"gitea": "https://Git.Live.Example./api"},
            ),
            ["git.live.example"],
        )

    def test_an_egress_grant_beyond_the_accounts_is_caught(self):
        roles = {
            "r": {
                "allow": [
                    "account(github/r):crud",
                    "egress(github.com)",
                    "egress(api.github.com)",
                    "egress(pastebin.example)",
                    "egress(${INFINITO_PACKAGE_CACHE})",
                ]
            }
        }
        self.assertEqual(
            _unaccounted_egress(roles, {"agent": ["r"]}),
            {"agent": ["pastebin.example"]},
        )


class TestNarrowOverride(unittest.TestCase):
    ROLES: ClassVar[dict] = {
        "r": {
            "allow": ["app(forge/issue):crud", "egress(github.com)"],
            "deny": ["app(upstream/push):create"],
        }
    }

    def _base(self) -> Resolved:
        return resolve(self.ROLES, "r")

    def test_an_added_deny_narrows(self):
        narrowed = narrow(self._base(), {"deny": ["app(forge/issue):delete"]})
        self.assertEqual(decide(narrowed, "app", "forge/issue", "delete"), "deny")
        self.assertEqual(decide(narrowed, "app", "forge/issue", "read"), "allow")

    def test_an_ask_on_a_granted_rule_narrows_allow_to_ask(self):
        narrowed = narrow(self._base(), {"ask": ["app(forge/issue):update"]})
        self.assertEqual(decide(narrowed, "app", "forge/issue", "update"), "ask")

    def test_every_widening_override_is_refused(self):
        for override in (
            {"allow": ["app(upstream/push):create"]},
            {"includes": ["maintainer"]},
            {"ask": ["app(upstream/push):create"]},
            {"ask": ["egress(evil.example)"]},
            {"ask": ["app(forge/*):read"]},
        ):
            with self.subTest(override=override), self.assertRaises(PermissionError):
                narrow(self._base(), override)

    def test_an_empty_override_changes_nothing(self):
        self.assertEqual(narrow(self._base(), {}), self._base())


class TestAskAtGate(unittest.TestCase):
    def test_an_ask_at_a_gate_node_is_asked(self):
        approve = {step.id: step for step in debug_ci.STEPS}["approve"]
        self.assertEqual(at_step("ask", approve.kind), "ask")

    def test_an_ask_outside_a_gate_node_is_a_misconfiguration(self):
        push = {step.id: step for step in debug_ci.STEPS}["push"]
        self.assertEqual(at_step("ask", push.kind), MISCONFIGURATION)
        self.assertEqual(at_step("ask", "deterministic"), MISCONFIGURATION)

    def test_allow_and_deny_pass_unchanged(self):
        self.assertEqual(at_step("allow", "deterministic"), "allow")
        self.assertEqual(at_step("deny", "ask"), "deny")


class TestAccountGrants(unittest.TestCase):
    ROLES: ClassVar[dict] = {
        "forge": {
            "allow": [
                "account(github/maintainer):crud",
                "account(gitea/maintainer):crud",
            ]
        },
        "lab": {"allow": ["account(gitlab/maintainer):crud"]},
    }

    def test_the_grants_follow_the_binding_then_the_rule_order(self):
        self.assertEqual(
            account_grants(self.ROLES, ["forge", "lab"]),
            ["github/maintainer", "gitea/maintainer", "gitlab/maintainer"],
        )

    def test_a_step_without_an_account_uses_the_first_active_grant(self):
        grants = account_grants(self.ROLES, ["forge", "lab"])
        everything = set(grants)
        self.assertEqual(default_account(grants, everything), "github/maintainer")
        self.assertEqual(
            default_account(grants, everything - {"github/maintainer"}),
            "gitea/maintainer",
        )
        self.assertIsNone(default_account(grants, set()))

    def test_reordering_the_binding_switches_the_default(self):
        grants = account_grants(self.ROLES, ["lab", "forge"])
        self.assertEqual(default_account(grants, set(grants)), "gitlab/maintainer")


class TestBaselineRoles(unittest.TestCase):
    """The shipped baseline roles grant what the design's baseline table lists."""

    VARIABLES: ClassVar[dict] = deploy_variables()
    TABLE = (
        ("workspace", "app", "workspace/worktree", "update", "allow"),
        ("workspace", "app", "docker/exec", "create", "deny"),
        ("workspace", "app", "workspace/foreign-stack", "read", "deny"),
        ("forge-reader", "egress", "api.github.com", None, "allow"),
        ("forge-reader", "app", "github/runs", "read", "allow"),
        ("package-consumer", "egress", "infinito-registry-cache.test", None, "allow"),
        ("package-consumer", "egress", "registry-1.docker.io", None, "deny"),
        ("interactive", "app", "workspace/worktree", "create", "allow"),
        ("interactive", "egress", "api.github.com", None, "allow"),
        ("interactive", "channel", "cross-session/all", "create", "allow"),
        ("interactive", "tool", "Edit", None, "allow"),
        ("interactive", "tool", "Bash(git commit*)", None, "ask"),
        ("interactive", "tool", "Bash(gh * comment*)", None, "ask"),
        ("interactive", "tool", "Bash(gh * close*)", None, "ask"),
        ("interactive", "tool", "Bash(git push*)", None, "deny"),
        ("autonomous-contributor", "app", "fork/push", "create", "allow"),
        ("autonomous-contributor", "app", "fork/force-push", "create", "ask"),
        ("autonomous-contributor", "app", "upstream/push", "create", "deny"),
        ("autonomous-contributor", "app", "github/merge", "create", "deny"),
        ("autonomous-contributor", "app", "github/secrets", "read", "deny"),
        ("maintainer", "app", "github/review-reply", "create", "allow"),
        ("maintainer", "app", "github/alert", "delete", "ask"),
        ("designer", "app", "artifact/gallery", "create", "allow"),
        ("designer", "app", "github/foreign-pull_request-comment", "create", "deny"),
        ("reviewer", "app", "github/review-comment", "create", "allow"),
        ("reviewer", "app", "github/own-pull_request-review", "create", "deny"),
        ("planner", "app", "openproject/work_packages", "update", "allow"),
        ("planner", "app", "openproject/approved", "update", "deny"),
        ("coordinator", "app", "ci/lock", "create", "allow"),
        ("coordinator", "app", "github/workflow", "delete", "ask"),
        ("coordinator", "app", "upstream/default-merge", "create", "deny"),
        ("operator", "app", "instance/metrics", "read", "allow"),
        ("operator", "app", "instance/backup-restore", "create", "ask"),
        ("operator", "app", "foreign-instance/all", "read", "deny"),
        ("tester", "app", "fork/push", "create", "allow"),
        ("documenter", "app", "fork/push", "create", "allow"),
        ("translator", "app", "weblate/suggestion", "create", "allow"),
        ("translator", "app", "weblate/reviewed", "update", "deny"),
        ("translator", "egress", "127.0.0.1:5555", None, "allow"),
        ("release", "app", "github/tag", "create", "ask"),
        ("release", "app", "upstream/default-push", "create", "deny"),
        ("security", "app", "openproject/security-project", "create", "allow"),
        ("security", "egress", "cloud.infinito-primary-domain.test", None, "deny"),
        ("hacker", "egress", "agents-hacker-targets.test", None, "allow"),
        ("hacker", "egress", "elsewhere.example", None, "deny"),
        ("hacker", "app", "hacker/production-run", "create", "ask"),
        ("hacker", "app", "hacker/denial-of-service", "create", "deny"),
        ("counsel", "app", "openproject/legal-project", "read", "allow"),
        ("counsel", "app", "fork/push", "create", "deny"),
        ("support", "app", "zammad/tickets", "read", "allow"),
        ("support", "app", "zammad/customer-reply", "create", "ask"),
        ("support", "app", "workspace/secrets", "read", "deny"),
    )

    def test_every_baseline_role_grants_its_table_row(self):
        roles = load_yaml(FIREWALL_ROLES)
        for role, kind, target, action, verdict in self.TABLE:
            with self.subTest(role=role, target=target, action=action):
                resolved = expand(resolve(roles, role), self.VARIABLES)
                self.assertEqual(decide(resolved, kind, target, action), verdict)

    def test_the_table_covers_every_baseline_role(self):
        self.assertEqual({row[0] for row in self.TABLE}, set(BASELINE))


class TestInteractiveSettings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="firewall_settings_")
        self.addCleanup(tmp.cleanup)
        self.settings = Path(tmp.name) / "settings.json"
        self.permissions = {
            "allow": ["Edit", "Bash(make *)"],
            "ask": ["Bash(git commit*)"],
            "deny": ["Bash(git push*)"],
            "additionalDirectories": ["/elsewhere"],
        }
        self.settings.write_text(
            json.dumps({"permissions": self.permissions}), encoding="utf-8"
        )
        self.roles = {
            "forge": {"allow": ["egress(github.com)"]},
            "session": {
                "includes": ["forge"],
                "settings": str(self.settings),
                "ask": ["app(github/commit):create"],
            },
        }

    def test_the_interactive_role_carries_exactly_the_permission_lists_of_the_file(
        self,
    ):
        settings = json.loads(read_text(str(SETTINGS)))["permissions"]
        compiled = managed_settings(resolve(load_yaml(FIREWALL_ROLES), "interactive"))
        self.assertEqual(
            compiled["permissions"],
            {verdict: settings[verdict] for verdict in VERDICTS},
        )

    def test_firewall_rules_beside_the_file_stay_out_of_the_managed_settings(self):
        resolved = resolve(self.roles, "session")
        self.assertEqual(
            managed_settings(resolved)["permissions"],
            {verdict: self.permissions[verdict] for verdict in VERDICTS},
        )
        self.assertEqual(decide(resolved, "egress", "github.com"), "allow")
        self.assertEqual(decide(resolved, "app", "github/commit", "create"), "ask")

    def test_a_tool_rule_matches_its_exact_text_only(self):
        resolved = resolve(self.roles, "session")
        for target, verdict in (
            ("Edit", "allow"),
            ("Bash(git commit*)", "ask"),
            ("Bash(git push*)", "deny"),
            ("Edit(README.md)", "deny"),
            ("Bash(make test)", "deny"),
            ("/elsewhere", "deny"),
        ):
            with self.subTest(target=target):
                self.assertEqual(decide(resolved, SETTINGS_KIND, target), verdict)

    def test_an_agent_that_may_not_write_keeps_only_the_tool_denies(self):
        gated = write_gate(
            resolve(self.roles, "session"),
            write_enabled=False,
            scenarios_passed=_ALL_PASSED,
        )
        self.assertEqual(
            managed_settings(gated)["permissions"],
            {"deny": ["Bash(git push*)"], "ask": [], "allow": []},
        )

    def test_a_shell_variable_in_a_tool_rule_is_not_a_deploy_variable(self):
        self.permissions["allow"].append("Bash(echo ${HOME_DIR})")
        self.settings.write_text(
            json.dumps({"permissions": self.permissions}), encoding="utf-8"
        )
        expanded = expand(resolve(self.roles, "session"), {})
        self.assertIn(
            "Bash(echo ${HOME_DIR})", managed_settings(expanded)["permissions"]["allow"]
        )


if __name__ == "__main__":
    unittest.main()
