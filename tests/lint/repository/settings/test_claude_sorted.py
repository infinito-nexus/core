import json
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SETTINGS_PATH = PROJECT_ROOT / ".claude" / "settings.json"

SORTED_ARRAYS: list[tuple[str, ...]] = [
    ("permissions", "allow"),
    ("permissions", "deny"),
    ("permissions", "ask"),
    ("sandbox", "network", "allowedDomains"),
    ("sandbox", "filesystem", "allowWrite"),
    ("sandbox", "filesystem", "denyRead"),
]


class TestClaudeSettingsSorted(unittest.TestCase):
    """Lint .claude/settings.json: every list-of-strings array we curate by hand
    must stay ASCII-sorted so diffs are reviewable and merge conflicts minimal."""

    @classmethod
    def setUpClass(cls) -> None:
        with Path(SETTINGS_PATH).open() as fh:
            cls.settings = json.load(fh)

    def test_arrays_are_ascending(self) -> None:
        for path in SORTED_ARRAYS:
            label = ".".join(path)
            with self.subTest(array=label):
                obj = self.settings
                for key in path:
                    obj = obj[key]
                self.assertEqual(
                    obj,
                    sorted(obj),
                    f"{label} is not ASCII-sorted ascending in {SETTINGS_PATH}. "
                    f"Fix: run `bash scripts/lint/claude.sh` "
                    f"(also wired into `scripts/lint/autoformat.sh`).",
                )


if __name__ == "__main__":
    unittest.main()
