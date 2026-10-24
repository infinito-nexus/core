"""L03: every role lists at least one skill; every skill a role lists exists in
agents/skills/; every routine a skill lists exists in agents/routines/."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tests.lint.agents import AGENTS_DIR, ROLES_DIR, load, role_names


def _skill_routines(skills_dir: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for skill_md in skills_dir.glob("*/SKILL.md"):
        front = skill_md.read_text(encoding="utf-8").split("---", 2)
        meta = yaml.safe_load(front[1]) if len(front) > 2 else {}
        out[skill_md.parent.name] = list((meta or {}).get("routines") or [])
    return out


def check(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    skills_dir = agents_dir / "skills"
    routines_dir = agents_dir / "routines"
    skills = _skill_routines(skills_dir)
    routines = {
        p.stem
        for p in routines_dir.glob("*.py")
        if not p.stem.startswith("_") and p.stem not in {"contract"}
    }
    for role in role_names(agents_dir / "roles"):
        listed = (load(agents_dir / "roles" / role / "agent.yml") or {}).get("skills") or []
        if not listed:
            problems.append(f"{role}: lists no skill")
        for skill in listed:
            if skill not in skills:
                problems.append(f"{role}: skill '{skill}' not in agents/skills/")
    for skill, routs in skills.items():
        for routine in routs:
            if routine not in routines:
                problems.append(f"{skill}: routine '{routine}' not in agents/routines/")
    return problems


class TestL03(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp)
            (agents / "roles" / "ghost").mkdir(parents=True)
            (agents / "roles" / "ghost" / "agent.yml").write_text(
                "skills: [i8-nope]\n", encoding="utf-8"
            )
            (agents / "skills").mkdir()
            (agents / "routines").mkdir()
            self.assertNotEqual(check(agents), [])


if __name__ == "__main__":
    unittest.main()
