"""L01: agent.yml has every field; runtime, lifecycle and firewall_roles name
known values; write_enabled defaults false; keepass.mode is broker or agent."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import (
    KEEPASS_MODES,
    LIFECYCLES,
    REQUIRED_AGENT_FIELDS,
    ROLES_DIR,
    RUNTIMES,
    load,
    role_names,
)

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
"""


def check(roles_dir: Path) -> list[str]:
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


class TestL01(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROLES_DIR), [])

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
            self.assertNotEqual(check(Path(tmp)), [])

    def test_unknown_trigger_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / "r"
            role.mkdir()
            role.joinpath("agent.yml").write_text(
                MINIMAL.replace("triggers: []", "triggers: [not_an_event]"),
                encoding="utf-8",
            )
            self.assertTrue(
                any("not a known event" in p for p in check(Path(tmp))),
                "unknown trigger not flagged",
            )


if __name__ == "__main__":
    unittest.main()
