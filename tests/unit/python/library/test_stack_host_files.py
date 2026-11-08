"""Unit tests for library/stack_host_files.py.

Exercises the building blocks (`render`, `survey`, `plan`, `apply`)
directly. The `main()` entrypoint is integration-tested through the
dashboard role's playbook — mocking AnsibleModule stdin/exit_json
end-to-end adds churn without catching additional logic bugs.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

MODULE_PATH = PROJECT_ROOT / "library" / "stack_host_files.py"

sys.path.insert(0, str(PROJECT_ROOT))


def _load_stack_host_files() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_stack_host_files", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_stack_host_files()


class TestRender(unittest.TestCase):
    def test_every_document_becomes_its_own_suffixed_file(self) -> None:
        out = _MOD.render({"de": {"Home": "Startseite"}, "en": {}}, ".yaml", 4, 100)
        self.assertEqual(sorted(out), ["de.yaml", "en.yaml"])

    def test_the_document_is_serialised_as_block_yaml(self) -> None:
        out = _MOD.render({"de": {"Home": "Startseite"}}, ".yaml", 4, 100)
        self.assertEqual(out["de.yaml"], "Home: Startseite\n")

    def test_non_ascii_survives_unescaped(self) -> None:
        out = _MOD.render({"de": {"Mail": "E-Mäil"}}, ".yaml", 4, 100)
        self.assertIn("E-Mäil", out["de.yaml"])

    def test_a_wide_width_keeps_a_long_scalar_on_one_line(self) -> None:
        long_value = "word " * 40
        out = _MOD.render({"de": {"K": long_value}}, ".yaml", 4, 100_000)
        self.assertEqual(len(out["de.yaml"].splitlines()), 1)


class TestSurvey(unittest.TestCase):
    def test_a_missing_directory_surveys_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_MOD.survey(Path(tmp) / "absent", ".yaml"), {})

    def test_only_files_carrying_the_suffix_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "de.yaml").write_text("a\n", encoding="utf-8")
            (directory / "notes.txt").write_text("b\n", encoding="utf-8")
            self.assertEqual(sorted(_MOD.survey(directory, ".yaml")), ["de.yaml"])


class TestPlan(unittest.TestCase):
    def _directory(self, tmp: str, files: dict[str, str]) -> dict[str, Path]:
        directory = Path(tmp)
        for name, content in files.items():
            (directory / name).write_text(content, encoding="utf-8")
        return _MOD.survey(directory, ".yaml")

    def test_a_missing_file_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            present = self._directory(tmp, {})
            written, removed = _MOD.plan(present, {"de.yaml": "a\n"}, True)
            self.assertEqual((written, removed), (["de.yaml"], []))

    def test_an_identical_file_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            present = self._directory(tmp, {"de.yaml": "a\n"})
            written, removed = _MOD.plan(present, {"de.yaml": "a\n"}, True)
            self.assertEqual((written, removed), ([], []))

    def test_a_differing_file_is_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            present = self._directory(tmp, {"de.yaml": "old\n"})
            written, removed = _MOD.plan(present, {"de.yaml": "new\n"}, True)
            self.assertEqual((written, removed), (["de.yaml"], []))

    def test_an_unwanted_file_is_removed_when_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            present = self._directory(tmp, {"de.yaml": "a\n", "en.yaml": "b\n"})
            written, removed = _MOD.plan(present, {"en.yaml": "b\n"}, True)
            self.assertEqual((written, removed), ([], ["de.yaml"]))

    def test_an_unwanted_file_survives_without_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            present = self._directory(tmp, {"de.yaml": "a\n"})
            written, removed = _MOD.plan(present, {}, False)
            self.assertEqual((written, removed), ([], []))


class TestApply(unittest.TestCase):
    def test_it_creates_the_directory_and_writes_with_the_given_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "content"
            wanted = {"de.yaml": "Home: Startseite\n"}
            _MOD.apply(directory, {}, wanted, ["de.yaml"], [], "0640", "0750")
            target = directory / "de.yaml"
            produced = target.read_text(
                encoding="utf-8"
            )  # nocheck: cache-read apply() wrote this file a line above; a cached read would serve the pre-write state
            self.assertEqual(produced, wanted["de.yaml"])
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o750)

    def test_it_drops_the_files_the_plan_marked_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            stale = directory / "de.yaml"
            stale.write_text("a\n", encoding="utf-8")
            present = _MOD.survey(directory, ".yaml")
            _MOD.apply(directory, present, {}, [], ["de.yaml"], "0644", "0755")
            self.assertFalse(stale.exists())

    def test_a_full_cycle_converges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "content"
            wanted = _MOD.render({"de": {"Home": "Startseite"}}, ".yaml", 4, 100)
            written, removed = _MOD.plan(_MOD.survey(directory, ".yaml"), wanted, True)
            _MOD.apply(directory, {}, wanted, written, removed, "0644", "0755")
            again = _MOD.plan(_MOD.survey(directory, ".yaml"), wanted, True)
            self.assertEqual(again, ([], []))


if __name__ == "__main__":
    unittest.main()
