from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.requires_python import requires_python, supported_minors


class TestRequiresPython(unittest.TestCase):
    def test_the_spec_is_read_from_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pyproject.toml").write_text(
                '[project]\nname = "demo"\nrequires-python = ">=3.11,<3.15"\n',
                encoding="utf-8",
            )
            self.assertEqual(requires_python(Path(tmp)), ">=3.11,<3.15")

    def test_the_range_admits_every_minor_below_the_cap(self) -> None:
        self.assertEqual(list(supported_minors(">=3.11,<3.15")), [11, 12, 13, 14])

    def test_another_shape_is_refused(self) -> None:
        for spec in (">=3.11", ">=3.11,<=3.14", "~=3.11", ">=3.11, <3.15"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                supported_minors(spec)


if __name__ == "__main__":
    unittest.main()
