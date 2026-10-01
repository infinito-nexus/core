from __future__ import annotations

import unittest
from pathlib import Path
from types import ModuleType

from utils.reexport import public_names


def _module(name: str = "pkg.__main__") -> ModuleType:
    """Return a module that defines one name and imported another."""
    module = ModuleType(name)
    module.Path = Path

    def run() -> None:
        """A name the module defines itself."""

    run.__module__ = name
    module.run = run
    module._private = object()
    return module


class TestPublicNames(unittest.TestCase):
    def test_an_imported_name_is_not_re_exported(self) -> None:
        self.assertEqual(public_names(_module()), ["run"])

    def test_an_imported_name_used_to_reach_the_package_namespace(self) -> None:
        module = _module()

        self.assertIn(
            "Path",
            [name for name in dir(module) if not name.startswith("_")],
            "listing dir() is what nine shims did, and it made Path a member of "
            "each of them, so sphinx found the same python target nine times",
        )

    def test_a_declared_all_is_taken_verbatim(self) -> None:
        module = _module()
        module.__all__ = ["Path", "run"]

        self.assertEqual(public_names(module), ["Path", "run"])

    def test_a_private_name_stays_private(self) -> None:
        self.assertNotIn("_private", public_names(_module()))


if __name__ == "__main__":
    unittest.main()
