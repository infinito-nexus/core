"""L01: agent.yml has every field; runtime, lifecycle and firewall_roles name
known values; write_enabled defaults false; keepass.mode is broker or agent;
every repositories entry is [<provider>/<label>:]<owner>/<name> and names only
an account the agent's firewall roles grant; workspace names a known kind, a
VM kind names an inventory host, runs on demand, runs a runtime of the VM
template and takes its size from resources."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import (
    AGENTS_DIR,
    AGENTS_INVENTORY,
    KEEPASS_MODES,
    LIFECYCLES,
    REQUIRED_AGENT_FIELDS,
    ROLES_DIR,
    RUNTIMES,
    load,
    role_names,
)
from utils.agents import vm_template, workspace
from utils.agents.accounts import repository_entry
from utils.firewall.compile import account_grants

INVENTORY_HOSTS = workspace.inventory_hosts(load(AGENTS_INVENTORY))
TEMPLATE_RUNTIMES = vm_template.runtimes(vm_template.TEMPLATE_DIR)
FIREWALL_ROLES = load(AGENTS_DIR / "firewall" / "roles.yml")

KNOWN_TRIGGERS = frozenset(
    {
        "alarm",
        "board_assignment",
        "branch_divergence",
        "channel_message",
        "ci_queue_change",
        "cve_feed",
        "default_branch_green",
        "dependency_manifest_changed",
        "deploy_finished",
        "issue_opened",
        "new_dependency",
        "pull_request_merged",
        "pull_request_opened",
        "pull_request_ready",
        "pull_request_updated",
        "security_alert",
        "spec_changed",
        "support_email",
        "support_room_message",
        "workflow_run_failed",
        "zammad_ticket",
    }
)

MINIMAL = """---
runtime: hermes
lifecycle: on_demand
owner: operator
repositories: [infinito-nexus/core]
firewall_roles: [interactive]
skills: [i8-commit]
models: {local: [ollama], external: [anthropic], default: anthropic}
keepass: {mode: broker}
write_enabled: false
triggers: []
quotas: {requests_per_minute: 60}
credentials: {}
workspace: {kind: server, model_access: gateway}
"""
SERVER = "{kind: server, model_access: gateway}"

VM = MINIMAL.replace("runtime: hermes", "runtime: claude-code").replace(
    SERVER,
    "{kind: incus, model_access: gateway, target: server, "
    "resources: {vcpu: 4, memory: 8g, disk: 64g}}",
)


def repository_problems(agent: dict, firewall_roles: dict) -> list[str]:
    """Return every malformed ``repositories`` entry and every entry naming an
    account outside the agent's account grants.

    Args:
        agent: the parsed agent.yml.
        firewall_roles: the parsed agents/firewall/roles.yml.
    """
    repositories = agent.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        return ["repositories must be a non-empty list"]
    grants = account_grants(firewall_roles, list(agent.get("firewall_roles") or []))
    problems: list[str] = []
    for raw in repositories:
        try:
            entry = repository_entry(raw)
        except ValueError as error:
            problems.append(str(error))
            continue
        if entry["account"] is not None and entry["account"] not in grants:
            problems.append(
                f"repositories entry {raw!r}: no account grant {entry['account']!r}"
            )
    return problems


def check(
    roles_dir: Path,
    inventory_hosts: frozenset[str],
    template_runtimes: frozenset[str],
    firewall_roles: dict,
) -> list[str]:
    problems: list[str] = []
    for role in role_names(roles_dir):
        agent = load(roles_dir / role / "agent.yml")
        if not isinstance(agent, dict):
            problems.append(f"{role}: agent.yml missing or not a mapping")
            continue
        problems.extend(
            f"{role}: agent.yml missing field '{field}'"
            for field in REQUIRED_AGENT_FIELDS
            if field not in agent
        )
        if "workspace" in agent:
            problems.extend(
                f"{role}: {problem}"
                for problem in workspace.problems(
                    agent, inventory_hosts, template_runtimes
                )
            )
        if agent.get("runtime") not in RUNTIMES:
            problems.append(f"{role}: runtime '{agent.get('runtime')}' unknown")
        if agent.get("lifecycle") not in LIFECYCLES:
            problems.append(f"{role}: lifecycle '{agent.get('lifecycle')}' unknown")
        if (agent.get("keepass") or {}).get("mode") not in KEEPASS_MODES:
            problems.append(f"{role}: keepass.mode must be broker or agent")
        if not isinstance(agent.get("firewall_roles"), list) or not agent.get(
            "firewall_roles"
        ):
            problems.append(f"{role}: firewall_roles must be a non-empty list")
        if "repositories" in agent:
            problems.extend(
                f"{role}: {problem}"
                for problem in repository_problems(agent, firewall_roles)
            )
        triggers = agent.get("triggers")
        if not isinstance(triggers, list):
            problems.append(f"{role}: triggers must be a list")
        else:
            problems.extend(
                f"{role}: trigger '{trigger}' is not a known event"
                for trigger in triggers
                if trigger not in KNOWN_TRIGGERS
            )
    return problems


def _check_one(text: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        role = Path(tmp) / "r"
        role.mkdir()
        role.joinpath("agent.yml").write_text(text, encoding="utf-8")
        return check(
            Path(tmp), frozenset({"server"}), TEMPLATE_RUNTIMES, FIREWALL_ROLES
        )


class TestL01(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(
            check(ROLES_DIR, INVENTORY_HOSTS, TEMPLATE_RUNTIMES, FIREWALL_ROLES), []
        )

    def test_a_repositories_entry_naming_a_granted_account_passes(self):
        named = MINIMAL.replace(
            "[infinito-nexus/core]", "[gitea/maintainer:infinito-nexus/core]"
        ).replace("[interactive]", "[maintainer]")
        self.assertEqual(_check_one(named), [])

    def test_a_malformed_or_ungranted_repositories_entry_fails(self):
        for entry, problem in (
            ("[core]", "expected [<provider>/<label>:]<owner>/<name>"),
            ("[gitea/maintainer:infinito-nexus/core]", "no account grant"),
            ("[]", "repositories must be a non-empty list"),
        ):
            with self.subTest(entry=entry):
                self.assertTrue(
                    any(
                        problem in p
                        for p in _check_one(
                            MINIMAL.replace("[infinito-nexus/core]", entry)
                        )
                    ),
                    entry,
                )

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good"
            (good).mkdir()
            (good / "agent.yml").write_text(MINIMAL, encoding="utf-8")
            broken = Path(tmp) / "broken"
            broken.mkdir()
            (broken / "agent.yml").write_text(
                MINIMAL.replace("runtime: hermes", "runtime: wizardry").replace(
                    "write_enabled: false\n", ""
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(
                check(Path(tmp), INVENTORY_HOSTS, TEMPLATE_RUNTIMES, FIREWALL_ROLES),
                [],
            )

    def test_unknown_trigger_fails(self):
        self.assertTrue(
            any(
                "not a known event" in p
                for p in _check_one(
                    MINIMAL.replace("triggers: []", "triggers: [not_an_event]")
                )
            ),
            "unknown trigger not flagged",
        )

    def test_vm_workspace_passes(self):
        self.assertEqual(_check_one(VM), [])

    def test_missing_workspace_fails(self):
        self.assertIn(
            "r: agent.yml missing field 'workspace'",
            _check_one(MINIMAL.replace(f"workspace: {SERVER}\n", "")),
        )

    def test_empty_or_partial_workspace_fails(self):
        for partial, missing in (
            ("{}", "workspace.kind is required"),
            ("{kind: server}", "workspace.model_access is required"),
            ("{model_access: gateway}", "workspace.kind is required"),
        ):
            self.assertIn(f"r: {missing}", _check_one(MINIMAL.replace(SERVER, partial)))

    def test_unknown_kind_fails(self):
        self.assertTrue(
            any(
                "workspace.kind 'docker'" in p
                for p in _check_one(MINIMAL.replace("kind: server", "kind: docker"))
            )
        )

    def test_unknown_workspace_key_fails(self):
        self.assertTrue(
            any(
                "workspace.vram is not a workspace key" in p
                for p in _check_one(
                    MINIMAL.replace(
                        SERVER, "{kind: server, model_access: gateway, vram: 8g}"
                    )
                )
            )
        )

    def test_host_kind_for_autonomous_role_fails(self):
        host = MINIMAL.replace("kind: server", "kind: host")
        autonomous = host.replace("[interactive]", "[autonomous-contributor]")
        self.assertEqual(_check_one(host), [])
        self.assertTrue(
            any("interactive role only" in p for p in _check_one(autonomous))
        )

    def test_vm_kind_needs_inventory_host_target(self):
        for broken in (
            VM.replace("target: server, ", ""),
            VM.replace("target: server", "target: ghost"),
        ):
            self.assertTrue(
                any("names an inventory host" in p for p in _check_one(broken)),
                broken,
            )

    def test_vm_kind_refused_always_on(self):
        self.assertTrue(
            any(
                "cannot run always_on" in p
                for p in _check_one(
                    VM.replace("lifecycle: on_demand", "lifecycle: always_on")
                )
            )
        )

    def test_vm_kind_refused_for_runtime_outside_template(self):
        self.assertTrue(
            any(
                "is not in the VM template" in p
                for p in _check_one(
                    VM.replace("runtime: claude-code", "runtime: hermes")
                )
            )
        )

    def test_vm_size_comes_from_resources(self):
        self.assertTrue(
            any(
                "workspace.resources.disk is missing" in p
                for p in _check_one(VM.replace(", disk: 64g", ""))
            )
        )
        self.assertTrue(
            any(
                "workspace.resources.vcpu must be positive" in p
                for p in _check_one(VM.replace("vcpu: 4", "vcpu: 0"))
            )
        )
        self.assertTrue(
            any(
                "applies to a VM kind only" in p
                for p in _check_one(
                    MINIMAL.replace(
                        SERVER,
                        "{kind: server, model_access: gateway, "
                        "resources: {vcpu: 1, memory: 1g, disk: 1g}}",
                    )
                )
            )
        )

    def test_model_access_is_gateway_or_login(self):
        login = MINIMAL.replace("model_access: gateway", "model_access: login")
        self.assertTrue(
            any("model_access login applies to" in p for p in _check_one(login))
        )
        self.assertTrue(
            any(
                "workspace.model_access 'apikey'" in p
                for p in _check_one(login.replace("login", "apikey"))
            )
        )


if __name__ == "__main__":
    unittest.main()
