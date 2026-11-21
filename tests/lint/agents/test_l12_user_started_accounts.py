"""L12: a user-started agent gets an account only on a provisioned provider. A
firewall role bound by an agent whose triggers a person initiates (a ticket, an
email, a chat or a room message) may grant account(<provider>/...) only for a
provider the provisioner creates accounts on, so a user cannot start an agent
that reaches an unprovisioned service. Checked through the compiler, so an
account inherited through an include is covered too."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, load, role_names
from utils.cache.yaml import dump_yaml_str
from utils.firewall.compile import resolve

PROVISIONED = {
    "github",
    "gitea",
    "gitlab",
    "openproject",
    "nextcloud",
    "matrix",
    "mail",
    "zammad",
}
USER_TRIGGERS = (
    "ticket",
    "email",
    "room_message",
    "chat",
    "message",
    "user_start",
    "mention",
)


def _user_started(triggers: list) -> bool:
    return any(
        any(token in str(trigger) for token in USER_TRIGGERS) for trigger in triggers
    )


def check(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    roles = load(agents_dir / "firewall" / "roles.yml") or {}
    for agent_role in role_names(agents_dir / "roles"):
        agent = load(agents_dir / "roles" / agent_role / "agent.yml") or {}
        if not _user_started(agent.get("triggers") or []):
            continue
        for firewall_role in agent.get("firewall_roles") or []:
            if firewall_role not in roles:
                continue
            resolved = resolve(roles, firewall_role)
            for rule in (*resolved.allow, *resolved.ask):
                if rule.kind != "account":
                    continue
                provider = str(rule.target).split("/", 1)[0]
                if provider not in PROVISIONED:
                    problems.append(
                        f"{agent_role}: user-started but '{firewall_role}' grants an "
                        f"account on unprovisioned provider '{provider}'"
                    )
    return problems


class TestL12(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp)
            (agents / "roles" / "chatty").mkdir(parents=True)
            (agents / "roles" / "chatty" / "agent.yml").write_text(
                dump_yaml_str(
                    {"triggers": ["support_room_message"], "firewall_roles": ["chatty"]}
                ),
                encoding="utf-8",
            )
            (agents / "firewall").mkdir()
            (agents / "firewall" / "roles.yml").write_text(
                dump_yaml_str({"chatty": {"allow": ["account(evilcorp/bot):read"]}}),
                encoding="utf-8",
            )
            self.assertNotEqual(check(agents), [])


if __name__ == "__main__":
    unittest.main()
