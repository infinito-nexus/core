from __future__ import annotations

import subprocess
import sys
import unittest

from . import PROJECT_ROOT, python_modules

_PACKAGES = ("cli", "plugins", "utils")
_MARK = "BROKEN-IMPORT "
_PROBE = f"""
import importlib
import sys

for name in sys.argv[2].split(","):
    try:
        importlib.import_module(name)
    except ImportError as error:
        if (error.name or "").split(".")[0] in sys.argv[1].split(","):
            print("{_MARK}" + name + ": " + str(error), flush=True)
    except BaseException:
        continue
"""


def _dotted(rel_path: str) -> str:
    """Return the module name a project file is imported under, empty when it has none.

    Args:
        rel_path: path relative to the project root.
    """
    parts = rel_path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if parts[0] not in _PACKAGES or not all(part.isidentifier() for part in parts):
        return ""
    return ".".join(parts)


class TestModulesImport(unittest.TestCase):
    def test_every_project_module_imports(self) -> None:
        names = sorted(
            {_dotted(rel) for rel, _content, _tree in python_modules()} - {""}
        )
        self.assertIn("cli.build.i18n.tune", names)

        result = subprocess.run(
            [sys.executable, "-c", _PROBE, ",".join(_PACKAGES), ",".join(names)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
        self.assertEqual(0, result.returncode, result.stderr[-2000:])
        broken = [
            line.removeprefix(_MARK)
            for line in result.stdout.splitlines()
            if line.startswith(_MARK)
        ]

        report = "\n".join(f"  - {line}" for line in broken)
        self.assertFalse(
            broken,
            f"{len(broken)} module(s) under {', '.join(_PACKAGES)} import a name "
            f"another project module no longer provides:\n{report}\n\n"
            "Import the name from the module that defines it.",
        )


class TestDottedName(unittest.TestCase):
    def test_a_module_maps_to_its_dotted_name(self) -> None:
        self.assertEqual("cli.build.i18n.tune", _dotted("cli/build/i18n/tune.py"))

    def test_a_package_init_maps_to_the_package(self) -> None:
        self.assertEqual("utils.cache", _dotted("utils/cache/__init__.py"))

    def test_a_path_outside_the_packages_has_none(self) -> None:
        self.assertEqual("", _dotted("roles/web-app-x/files/a.py"))

    def test_a_hyphenated_directory_has_none(self) -> None:
        self.assertEqual("", _dotted("plugins/x-y/a.py"))


if __name__ == "__main__":
    unittest.main()
