from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.repository.documentation import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

SKILLS_DIR = PROJECT_ROOT / "agents" / "skills"


def check(skills_dir: Path) -> list[str]:
    """
    Args:
        skills_dir: the directory holding one ``<skill>/SKILL.md`` per skill.
    """
    problems: list[str] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        parts = read_text(str(skill_md)).split("---", 2)
        meta = load_yaml_str(parts[1]) if len(parts) > 2 else None
        name = meta.get("name") if isinstance(meta, dict) else None
        if name != skill_md.parent.name:
            problems.append(
                f"{skill_md.parent.name}: frontmatter name is {name!r}, "
                f"expected {skill_md.parent.name!r}"
            )
    return problems


class TestSkillNameMatchesDirectory(unittest.TestCase):
    def test_real_tree_passes(self) -> None:
        self.assertEqual(check(SKILLS_DIR), [])

    def test_renamed_directory_with_the_old_name_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "i8-tune-velocity"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: i8-tuner\ndescription: x\n---\n\nBody.\n",
                encoding="utf-8",
            )
            self.assertEqual(
                check(Path(tmp)),
                [
                    (
                        "i8-tune-velocity: frontmatter name is 'i8-tuner', "
                        "expected 'i8-tune-velocity'"
                    )
                ],
            )

    def test_skill_without_frontmatter_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "i8-bare"
            skill.mkdir()
            (skill / "SKILL.md").write_text("# Bare\n", encoding="utf-8")
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
