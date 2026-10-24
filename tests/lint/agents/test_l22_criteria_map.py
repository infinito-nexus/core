"""L22: agents/criteria.yml maps every criterion to exactly one proof kind and
an existing proof. A criterion that asks for a probe, a refusal, a time bound
or a restart is proven by a scenario, never by a lint or a unit test."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tests.lint.agents import PROJECT_ROOT

CRITERIA = PROJECT_ROOT / "agents" / "criteria.yml"
KINDS = ("lint", "unit", "scenario")
SCENARIO_WORDS = ("probe", "refus", "refuse", "time bound", "restart", "locks no", "waits for")


def check(criteria_file: Path, root: Path) -> list[str]:
    problems: list[str] = []
    data = yaml.safe_load(criteria_file.read_text(encoding="utf-8")) if criteria_file.is_file() else None
    if not isinstance(data, dict):
        return ["criteria.yml missing or not a mapping"]
    for cid, entry in data.items():
        if not isinstance(entry, dict):
            problems.append(f"{cid}: not a mapping")
            continue
        kind = entry.get("proof_kind")
        proof = entry.get("proof")
        statement = str(entry.get("statement") or "")
        if kind not in KINDS:
            problems.append(f"{cid}: proof_kind '{kind}' not one of {KINDS}")
        if not statement:
            problems.append(f"{cid}: no statement")
        if not proof or not (root / proof).exists():
            problems.append(f"{cid}: proof '{proof}' does not exist")
        if kind != "scenario" and any(w in statement.lower() for w in SCENARIO_WORDS):
            problems.append(f"{cid}: asks for a probe/refusal/time/restart but is not a scenario")
        if kind == "scenario" and proof and not str(proof).startswith("agents/scenarios/"):
            problems.append(f"{cid}: scenario proof must live under agents/scenarios/")
    return problems


class TestL22(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(CRITERIA, PROJECT_ROOT), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            crit = Path(tmp) / "criteria.yml"
            crit.write_text(
                yaml.safe_dump(
                    {"X": {"statement": "the firewall refuses the request (probe)", "proof_kind": "lint", "proof": "nope.py"}}
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(check(crit, Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
