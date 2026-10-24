"""L23: every lint or unit proof ships a red fixture, a deliberately broken
input the proof catches, so a proof that can never fail is itself caught."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tests.lint.agents import PROJECT_ROOT
from utils.cache.files import read_text

CRITERIA = PROJECT_ROOT / "agents" / "criteria.yml"
RED_MARKERS = ("def test_red_fixture_fails", "red fixture", "red_fixture")


def check(criteria_file: Path, root: Path) -> list[str]:
    problems: list[str] = []
    data = yaml.safe_load(read_text(str(criteria_file))) if criteria_file.is_file() else None
    if not isinstance(data, dict):
        return ["criteria.yml missing or not a mapping"]
    for cid, entry in data.items():
        if not isinstance(entry, dict) or entry.get("proof_kind") not in ("lint", "unit"):
            continue
        proof = root / str(entry.get("proof"))
        if not proof.is_file():
            problems.append(f"{cid}: proof file missing")
            continue
        text = read_text(str(proof))
        if not any(marker in text for marker in RED_MARKERS):
            problems.append(f"{cid}: lint or unit proof has no red fixture")
    return problems


class TestL23(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(CRITERIA, PROJECT_ROOT), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "no_red.py").write_text("def test_real_only(): pass\n", encoding="utf-8")
            crit = root / "criteria.yml"
            crit.write_text(
                yaml.safe_dump({"X": {"statement": "x", "proof_kind": "lint", "proof": "tests/no_red.py"}}),
                encoding="utf-8",
            )
            self.assertNotEqual(check(crit, root), [])


if __name__ == "__main__":
    unittest.main()
