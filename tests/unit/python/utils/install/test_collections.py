import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.install.collections import declared_pins, unsatisfied

_REQUIREMENTS = (
    PROJECT_ROOT / "requirements" / "requirements.galaxy.yml",
    PROJECT_ROOT / "requirements" / "requirements.git.yml",
)

_BOOTSTRAP_PROBE = """
import sys


class _NoPyYAML:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "yaml" or fullname.startswith("yaml."):
            raise ImportError("PyYAML is absent during the lint bootstrap")
        return None


sys.meta_path.insert(0, _NoPyYAML())

from pathlib import Path

from utils.install.lint.ansible import collections as lint_collections
from utils.install.collections import declared_pins

for fqcn, version in declared_pins(Path("requirements/requirements.galaxy.yml")):
    print(fqcn, version)
"""

REQUIREMENTS = """---
collections:
  - name: community.general
    version: 13.4.0
  - name: hetzner.hcloud
    version: 7.0.1
"""


def _write_requirements(root: Path, body: str = REQUIREMENTS) -> Path:
    path = root / "requirements.galaxy.yml"
    path.write_text(body, encoding="utf-8")
    return path


def _install(collections_dir: Path, fqcn: str, version: str) -> None:
    namespace, _, name = fqcn.partition(".")
    target = collections_dir / "ansible_collections" / namespace / name
    target.mkdir(parents=True)
    (target / "MANIFEST.json").write_text(
        json.dumps({"collection_info": {"version": version}}), encoding="utf-8"
    )


class TestAgainstPyYAML(unittest.TestCase):
    def test_the_hand_parser_agrees_with_pyyaml(self):
        for path in _REQUIREMENTS:
            with self.subTest(requirements=path.name):
                declared = load_yaml_any(str(path), default_if_missing={}) or {}
                expected = [
                    (str(entry.get("name")), entry.get("version"))
                    for entry in declared.get("collections") or []
                    if isinstance(entry, dict) and entry.get("name")
                ]
                expected = [
                    (name, None if version is None else str(version))
                    for name, version in expected
                ]

                self.assertEqual(declared_pins(path), expected)

    def test_the_parser_runs_with_pyyaml_unimportable(self):
        result = subprocess.run(
            [sys.executable, "-c", _BOOTSTRAP_PROBE],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("community.general", result.stdout)


class TestDeclaredPins(unittest.TestCase):
    def test_a_quoted_version_is_read_without_its_quotes(self):
        body = (
            "---\ncollections:\n"
            '  - name: double.quoted\n    version: "13.4.0"\n'
            "  - name: single.quoted\n    version: '1.0.0'\n"
            "  - name: commented\n    version: 2.2.2 # pinned\n"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = _write_requirements(root, body)

            self.assertEqual(
                declared_pins(requirements),
                [
                    ("double.quoted", "13.4.0"),
                    ("single.quoted", "1.0.0"),
                    ("commented", "2.2.2"),
                ],
            )

    def test_an_entry_without_a_version_stays_unpinned(self):
        body = "---\ncollections:\n  - name: bare.entry\n"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)

            self.assertEqual(
                declared_pins(_write_requirements(root, body)), [("bare.entry", None)]
            )

    def test_a_missing_file_declares_nothing(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(declared_pins(Path(tmp) / "absent.yml"), [])


class TestUnsatisfied(unittest.TestCase):
    def test_every_pin_installed_at_its_version_is_satisfied(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = _write_requirements(root)
            _install(root, "community.general", "13.4.0")
            _install(root, "hetzner.hcloud", "7.0.1")

            self.assertEqual(unsatisfied(requirements, root), [])

    def test_absent_collection_is_reported(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = _write_requirements(root)
            _install(root, "community.general", "13.4.0")

            self.assertEqual(unsatisfied(requirements, root), ["hetzner.hcloud:7.0.1"])

    def test_wrong_version_is_reported_although_the_directory_exists(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = _write_requirements(root)
            _install(root, "community.general", "13.4.0")
            _install(root, "hetzner.hcloud", "6.9.0")

            self.assertEqual(unsatisfied(requirements, root), ["hetzner.hcloud:7.0.1"])

    def test_unpinned_entry_can_never_be_confirmed(self):
        body = "---\ncollections:\n  - name: community.general\n"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = _write_requirements(root, body)
            _install(root, "community.general", "13.4.0")

            self.assertEqual(unsatisfied(requirements, root), ["community.general"])

    def test_unreadable_manifest_is_reported(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = _write_requirements(root)
            _install(root, "community.general", "13.4.0")
            _install(root, "hetzner.hcloud", "7.0.1")
            manifest = (
                root / "ansible_collections" / "hetzner" / "hcloud" / "MANIFEST.json"
            )
            manifest.write_text("{not json", encoding="utf-8")

            self.assertEqual(unsatisfied(requirements, root), ["hetzner.hcloud:7.0.1"])


if __name__ == "__main__":
    unittest.main()
