from __future__ import annotations

import re
import unittest

from utils import PROJECT_ROOT
from utils.cache.evict import CACHES, FLOOR_KEY, IDLE_KEY
from utils.cache.files import read_text
from utils.env.handlers.infinito.cache import conf, pin

DOC = PROJECT_ROOT / "docs" / "contributing" / "environment" / "cache.md"
TARGETS = ("make cache-evict", "make cache-status")
PIN_NAMES = (pin.KEY, pin.ROOT_KEY, conf.KEY, "make cache-declare ref=<commit>")
NO_PIN = "Without a pin"
ROLLOUT = (
    "make dotenv-force",
    "make cache-declare ref=<merge commit>",
    conf.RELATIVE.as_posix(),
    "A worktree still on older code",
)
_PROFILE = re.compile(
    r"(compose\s+)?profile\s*\(?`cache`\)?|`cache`\s+(compose\s+)?profile",
    re.IGNORECASE,
)


class TestCacheDocBounds(unittest.TestCase):
    def test_the_doc_names_every_cap_the_window_the_floor_and_both_targets(
        self,
    ) -> None:
        text = read_text(str(DOC))
        missing = [
            name
            for name in (
                *(spec.cap_key for spec in CACHES),
                IDLE_KEY,
                FLOOR_KEY,
                *TARGETS,
            )
            if name not in text
        ]
        self.assertEqual(missing, [])

    def test_the_doc_describes_the_eviction_of_every_cache(self) -> None:
        text = read_text(str(DOC))
        section = text.split("## Bounds and Eviction", 1)[1].split("\n## ", 1)[0]
        for row in (
            "Registry mirror",
            "Nexus",
            "Shared folders",
            "Models",
            "Host build cache",
        ):
            self.assertRegex(section, rf"\n\| {row} \|")

    def test_the_doc_covers_the_pin_its_absence_and_the_rollout(self) -> None:
        section = (
            read_text(str(DOC))
            .split("## Adding a New Upstream", 1)[1]
            .split("\n## ", 1)[0]
        )
        missing = [
            name for name in (*PIN_NAMES, NO_PIN, *ROLLOUT) if name not in section
        ]
        self.assertEqual(missing, [])

    def test_the_doc_names_no_cache_profile(self) -> None:
        self.assertIsNone(_PROFILE.search(read_text(str(DOC))))

    def test_the_profile_detector_catches_the_old_wording(self) -> None:
        self.assertIsNotNone(
            _PROFILE.search(
                "They share one compose profile (`cache`) and one override file"
            )
        )


if __name__ == "__main__":
    unittest.main()
