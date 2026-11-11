"""Lint: every agent runtime declares itself in its role metadata.

A runtime role carries ``agent_runtime`` (``name`` and ``host``) on the service
entry that serves it, each runtime name is declared once, and every runtime an
``agents/roles/*/agent.yml`` names is declared by a role. The broker, the
orchestrator and the agents lints read the runtimes from these declarations.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import ROLES_DIR, declared_runtimes, load, role_names
from utils.agents import runtimes

from . import PROJECT_ROOT

EXPECTED = {
    "hermes": ("web-app-hermes", "broker"),
    "openclaw": ("web-app-openclaw", "broker"),
    "claude-code": ("web-app-workspace", "workspace"),
}


def named_runtimes(agent_roles_dir: Path) -> dict[str, str]:
    return {
        role: (load(agent_roles_dir / role / "agent.yml") or {}).get("runtime")
        for role in role_names(agent_roles_dir)
    }


def check(project_root: Path, agent_roles_dir: Path) -> list[str]:
    try:
        found = declared_runtimes(project_root)
    except ValueError as error:
        return [str(error)]
    return runtimes.problems(found, named_runtimes(agent_roles_dir))


def _write_services(root: Path, role: str, text: str) -> None:
    meta = root / "roles" / role / "meta"
    meta.mkdir(parents=True)
    (meta / "services.yml").write_text(text, encoding="utf-8")


class TestAgentRuntimeDeclared(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(PROJECT_ROOT, ROLES_DIR), [])

    def test_the_three_runtimes_declare_themselves_in_their_roles(self):
        found = declared_runtimes(PROJECT_ROOT)
        self.assertEqual(
            {
                name: (entry["application_id"], entry["host"])
                for name, entry in found.items()
            },
            EXPECTED,
        )

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_services(
                root,
                "web-app-a",
                "a:\n  agent_runtime:\n    name: a\n    host: cloud\n",
            )
            agent = root / "agents" / "roles" / "robot"
            agent.mkdir(parents=True)
            (agent / "agent.yml").write_text("runtime: missing\n", encoding="utf-8")
            found = check(root, root / "agents" / "roles")
            self.assertEqual(len(found), 2, found)
            self.assertIn("host of", found[0])
            self.assertIn("runtime 'missing' is declared by no role", found[1])

    def test_a_runtime_declared_twice_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = "s:\n  agent_runtime:\n    name: a\n    host: broker\n"
            _write_services(root, "web-app-a", entry)
            _write_services(root, "web-app-b", entry)
            found = check(root, root / "agents" / "roles")
            self.assertEqual(len(found), 1, found)
            self.assertIn("declared by web-app-a (s) and web-app-b (s)", found[0])


if __name__ == "__main__":
    unittest.main()
