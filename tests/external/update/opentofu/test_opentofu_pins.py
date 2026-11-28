from __future__ import annotations

import unittest

from utils.annotations.message import warning
from utils.update.opentofu import collect_pins, find_outdated_updates

from . import PROJECT_ROOT


class TestOpenTofuPins(unittest.TestCase):
    def test_opentofu_provider_pins(self) -> None:
        self.assertTrue(collect_pins(PROJECT_ROOT), "No OpenTofu provider pins found")
        for update in find_outdated_updates(PROJECT_ROOT):
            warning(
                f"{update.pin.role}: {update.pin.source} is pinned at "
                f"{update.pin.version}, latest in the OpenTofu registry is "
                f"{update.latest}",
                title="Outdated OpenTofu provider pin",
                file=str(update.pin.path.relative_to(PROJECT_ROOT)),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
