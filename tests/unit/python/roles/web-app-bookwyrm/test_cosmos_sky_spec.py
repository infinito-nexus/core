from __future__ import annotations

import json
import re
import unittest

from tests.lint.filesystem.test_cosmos_sheets import (
    CLEAR,
    ROLES,
    SHEET,
    SURFACE,
    render,
    rules,
    selectors,
)
from utils.cache.files import read_text

ROLE = ROLES / "web-app-bookwyrm"
SPEC = ROLE / "files" / "playwright" / "test-design.js"
CLEARED = re.compile(r"^const SKY_CLEARED = (\[[^\]]*\]);$", re.MULTILINE)


def cleared_by_sheet(text: str) -> list[str]:
    """
    Args:
        text: a cosmos sheet template.

    Returns:
        Every selector the sheet clears under the sky, with the sky prefix
        and any trailing ``:not(...)`` filter removed.
    """
    sky, top = selectors()
    found = []
    for chosen, declared in rules(render(text, sky, top)):
        if not any(declared.get(prop) in CLEAR for prop in SURFACE):
            continue
        for selector in chosen:
            if selector == sky:
                found.append("html")
            elif selector.startswith(f"{sky} ") and not selector.startswith(top):
                found.append(selector[len(sky) :].strip().split(":not(", 1)[0])
    return found


def spec_cleared(text: str) -> list[str]:
    """
    Args:
        text: the Playwright design spec.

    Returns:
        The ``SKY_CLEARED`` selectors the spec hands to ``assertSky``.
    """
    match = CLEARED.search(text)
    if match is None:
        raise AssertionError(f"{SPEC} defines no SKY_CLEARED list")
    return json.loads(match.group(1))


class TestBookwyrmCosmosSkySpec(unittest.TestCase):
    def setUp(self) -> None:
        self.sheet = read_text(str(ROLE / SHEET))
        self.spec = read_text(str(SPEC))

    def test_the_spec_probes_what_the_sheet_clears(self) -> None:
        missing = sorted(
            set(spec_cleared(self.spec)) - set(cleared_by_sheet(self.sheet))
        )
        self.assertEqual(
            missing,
            [],
            "assertSky reads the first match of each SKY_CLEARED selector; a "
            "bare 'footer' hits the hidden modal-card-foot before the page "
            ".footer the sheet clears",
        )

    def test_a_bare_footer_probe_is_caught(self) -> None:
        planted = self.spec.replace('".footer"]', '"footer"]', 1)
        self.assertNotEqual(planted, self.spec)
        self.assertIn(
            "footer",
            set(spec_cleared(planted)) - set(cleared_by_sheet(self.sheet)),
        )


if __name__ == "__main__":
    unittest.main()
