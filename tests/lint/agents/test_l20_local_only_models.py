"""L20: support, planner, operator and user-started agents default to local
models only; their agent.yml lists no external model."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import LOCAL_ONLY_ROLES, ROLES_DIR, load, role_names


def check(roles_dir: Path) -> list[str]:
    problems: list[str] = []
    present = set(role_names(roles_dir))
    for role in LOCAL_ONLY_ROLES:
        if role not in present:
            continue
        models = (load(roles_dir / role / "agent.yml") or {}).get("models") or {}
        if (models.get("external") or []) != []:
            problems.append(
                f"{role}: must be local-only, external={models.get('external')!r}"
            )
        if models.get("default") in (models.get("external") or []):
            problems.append(f"{role}: default model is external")
    return problems


class TestL20(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROLES_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / "planner"
            role.mkdir()
            (role / "agent.yml").write_text(
                "models: {local: [ollama], external: [anthropic], default: anthropic}\n",
                encoding="utf-8",
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
