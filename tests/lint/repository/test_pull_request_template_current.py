from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from cli.contributing.pull_request.body import (
    AREA_DIR,
    DEFAULT,
    areas,
    generated,
    stale,
    variables,
)
from utils.cache.files import PROJECT_ROOT, read_text

CONTRACT = (
    PROJECT_ROOT / "docs" / "contributing" / "artefact" / "git" / "pull-request.md"
)
_ROW = re.compile(r"^\| `(?P<name>[a-z_]+)` \|", re.MULTILINE)
PROMPTS = ("lead", "feature", "fix", "affected", "security", "risk", "notes")
PROMPT_LISTS = ("examples", "components", "details", "focus", "integrations")


def documented() -> frozenset[str]:
    text = read_text(str(CONTRACT))
    contract = text.split("### Variables", 1)[1].split("\n## ", 1)[0]
    return frozenset(_ROW.findall(contract))


def copied(tmp: str) -> dict[Path, str]:
    """Write the current renders under ``tmp`` and return them keyed by copy."""
    copies = {}
    for path, text in generated().items():
        copy = Path(tmp) / path.relative_to(PROJECT_ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(text, encoding="utf-8")
        copies[copy] = text
    return copies


class TestPullRequestTemplateCurrent(unittest.TestCase):
    def test_every_generated_file_is_current(self) -> None:
        self.assertEqual(
            stale(), [], "run python -m cli.contributing.pull_request default"
        )

    def test_the_generated_set_is_the_chooser_and_one_file_per_area(self) -> None:
        expected = {DEFAULT} | {
            AREA_DIR / f"{scope}.md" for scope in areas() if scope != "general"
        }
        self.assertEqual(set(generated()), expected)

    def test_a_hand_edited_area_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copies = copied(tmp)
            self.assertEqual(stale(copies), [])
            server = next(p for p in copies if p.name == "server.md")
            edited = server.with_name("server-edited.md")
            edited.write_text(copies[server] + "hand edit\n", encoding="utf-8")
            expected = {**copies, edited: copies[server]}
            del expected[server]
            reasons = stale(expected)
            self.assertEqual(len(reasons), 1)
            self.assertIn("server-edited.md is not the current render", reasons[0])

    def test_a_missing_area_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copies = copied(tmp)
            agents = next(p for p in copies if p.name == "agents.md")
            agents.unlink()
            reasons = stale(copies)
            self.assertEqual(len(reasons), 1)
            self.assertIn("agents.md is missing", reasons[0])

    def test_no_generated_file_holds_a_placeholder(self) -> None:
        for path in generated():
            with self.subTest(path=path.name):
                text = read_text(str(path))
                self.assertNotIn("{{", text)
                self.assertNotIn("{%", text)

    def test_every_area_prompt_reaches_its_web_template(self) -> None:
        for scope, area in areas().items():
            if scope == "general":
                continue
            text = read_text(str(AREA_DIR / f"{scope}.md"))
            prompts = [area[key] for key in PROMPTS]
            prompts += [item for key in PROMPT_LISTS for item in area[key]]
            prompts += [label for _id, label in area["checks"]]
            for prompt in prompts:
                with self.subTest(scope=scope, prompt=prompt):
                    self.assertIn(prompt, text)

    def test_the_chooser_names_every_area_template(self) -> None:
        text = read_text(str(DEFAULT))
        for scope in areas():
            if scope != "general":
                with self.subTest(scope=scope):
                    self.assertIn(f"`template={scope}.md`", text)

    def test_the_contract_documents_every_variable(self) -> None:
        self.assertEqual(documented(), variables())


if __name__ == "__main__":
    unittest.main()
