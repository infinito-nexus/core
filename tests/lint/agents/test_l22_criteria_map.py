"""L22: agents/criteria.yml maps every criterion to exactly one proof kind and
an existing proof, and every proof to a criterion: a scenario under
``agents/scenarios/`` or a catalog lint under ``tests/lint/agents/`` that no
criterion names fails, and so does a scenario whose ``criterion`` field names
a criterion that does not point back at it. A criterion that asks for a probe,
a refusal, a time bound or a restart is proven by a scenario, never by a lint
or a unit test. A lint-proven criterion names a catalog lint id, and its proof
is that lint's file under tests/lint/agents/."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.cache.yaml import dump_yaml_str, load_yaml_any

CRITERIA = PROJECT_ROOT / "agents" / "criteria.yml"
SCENARIOS = Path("agents") / "scenarios"
CATALOG_LINTS = Path("tests") / "lint" / "agents"
LINTS = PROJECT_ROOT / CATALOG_LINTS
KINDS = ("lint", "unit", "scenario")
_LINT_FILE = re.compile(r"^test_l(\d{2})_\w+\.py$")
SCENARIO_WORDS = (
    "probe",
    "refus",
    "refuse",
    "time bound",
    "restart",
    "locks no",
    "waits for",
)


def catalog(lints_dir: Path) -> dict[str, str]:
    """Return every catalog lint id with its file name, e.g. ``L06``.

    Args:
        lints_dir: the tests/lint/agents directory.
    """
    found: dict[str, str] = {}
    for path in sorted(lints_dir.glob("test_l*_*.py")):
        match = _LINT_FILE.match(path.name)
        if match:
            found[f"L{match.group(1)}"] = path.name
    return found


def lint_id_problems(cid: str, proof: str, lints: dict[str, str]) -> list[str]:
    """Return why a lint-proven criterion does not name its catalog lint.

    Args:
        cid: the criterion id, a catalog lint id such as ``L06``.
        proof: the proof path the criterion names.
        lints: the catalog, as ``catalog`` returns it.
    """
    if cid not in lints:
        return [f"{cid}: lint-proven but not a catalog lint id {sorted(lints)}"]
    if Path(str(proof)).name != lints[cid]:
        return [f"{cid}: proof '{proof}' is not the lint {lints[cid]}"]
    return []


def check(criteria_file: Path, root: Path, lints_dir: Path) -> list[str]:
    problems: list[str] = []
    data = (
        load_yaml_any(str(criteria_file), default_if_missing={})
        if criteria_file.is_file()
        else None
    )
    if not isinstance(data, dict):
        return ["criteria.yml missing or not a mapping"]
    lints = catalog(lints_dir)
    for cid, entry in data.items():
        if not isinstance(entry, dict):
            problems.append(f"{cid}: not a mapping")
            continue
        kind = entry.get("proof_kind")
        proof = entry.get("proof")
        statement = str(entry.get("statement") or "")
        if kind not in KINDS:
            problems.append(f"{cid}: proof_kind '{kind}' not one of {KINDS}")
        if kind == "lint":
            problems.extend(lint_id_problems(str(cid), str(proof), lints))
        if not statement:
            problems.append(f"{cid}: no statement")
        if not proof or not (root / proof).exists():
            problems.append(f"{cid}: proof '{proof}' does not exist")
        if kind != "scenario" and any(w in statement.lower() for w in SCENARIO_WORDS):
            problems.append(
                f"{cid}: asks for a probe/refusal/time/restart but is not a scenario"
            )
        if (
            kind == "scenario"
            and proof
            and not str(proof).startswith("agents/scenarios/")
        ):
            problems.append(f"{cid}: scenario proof must live under agents/scenarios/")
    return problems + _unclaimed_proofs(data, root)


def _unclaimed_proofs(data: dict, root: Path) -> list[str]:
    """Return a problem per scenario or catalog lint no criterion claims.

    Args:
        data: the parsed criteria mapping.
        root: the tree the proofs are looked up in.
    """
    claimed = {
        str(entry.get("proof")): str(cid)
        for cid, entry in data.items()
        if isinstance(entry, dict)
    }
    problems: list[str] = []
    for path in sorted((root / SCENARIOS).glob("*.yml")):
        relative = str(path.relative_to(root))
        owner = claimed.get(relative)
        if owner is None:
            problems.append(f"{relative}: proves no criterion of criteria.yml")
            continue
        named = (load_yaml_any(str(path), default_if_missing={}) or {}).get("criterion")
        if named != owner:
            problems.append(
                f"{relative}: names criterion '{named}', but '{owner}' claims it"
            )
    for path in sorted((root / CATALOG_LINTS).glob("test_l[0-9]*.py")):
        relative = str(path.relative_to(root))
        if relative not in claimed:
            problems.append(f"{relative}: proves no criterion of criteria.yml")
    return problems


class TestL22(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(CRITERIA, PROJECT_ROOT, LINTS), [])

    def test_red_fixture_proof_without_criterion_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / SCENARIOS).mkdir(parents=True)
            (root / CATALOG_LINTS).mkdir(parents=True)
            (root / SCENARIOS / "claimed.yml").write_text(
                "criterion: SC-CLAIMED\n", encoding="utf-8"
            )
            (root / SCENARIOS / "orphan.yml").write_text(
                "criterion: SC-GHOST\n", encoding="utf-8"
            )
            (root / CATALOG_LINTS / "test_l99_orphan.py").write_text(
                "def test_red_fixture_fails(): pass\n", encoding="utf-8"
            )
            crit = root / "criteria.yml"
            crit.write_text(
                dump_yaml_str(
                    {
                        "SC-CLAIMED": {
                            "statement": "a claimed scenario",
                            "proof_kind": "scenario",
                            "proof": str(SCENARIOS / "claimed.yml"),
                        }
                    }
                ),
                encoding="utf-8",
            )
            unclaimed = ": proves no criterion of criteria.yml"
            self.assertEqual(
                check(crit, root, root / CATALOG_LINTS),
                [
                    f"agents/scenarios/orphan.yml{unclaimed}",
                    f"tests/lint/agents/test_l99_orphan.py{unclaimed}",
                ],
            )
            (root / SCENARIOS / "claimed.yml").write_text(
                "criterion: SC-OTHER\n", encoding="utf-8"
            )
            self.assertIn(
                "agents/scenarios/claimed.yml: names criterion 'SC-OTHER', but "
                "'SC-CLAIMED' claims it",
                check(crit, root, root / CATALOG_LINTS),
            )

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            crit = Path(tmp) / "criteria.yml"
            crit.write_text(
                dump_yaml_str(
                    {
                        "X": {
                            "statement": "the firewall refuses the request (probe)",
                            "proof_kind": "lint",
                            "proof": "nope.py",
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(check(crit, Path(tmp), LINTS), [])

    def test_a_criterion_naming_a_missing_lint_id_fails(self):
        lints = catalog(LINTS)
        self.assertIn("L06", lints)
        self.assertNotEqual(
            lint_id_problems("L99", "tests/lint/agents/test_l99_ghost.py", lints), []
        )
        self.assertNotEqual(
            lint_id_problems("L05", f"tests/lint/agents/{lints['L07']}", lints), []
        )
        self.assertEqual(
            lint_id_problems("L05", f"tests/lint/agents/{lints['L05']}", lints), []
        )


if __name__ == "__main__":
    unittest.main()
