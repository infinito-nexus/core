"""Every service an override extends must be defined by a base compose file.

An override that names a service nobody declares renders as an incomplete
service, and `docker compose config` rejects the whole project with "has
neither an image nor a build context". The failure hits every compose call of
the dev tooling, not just the override that introduced it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import ClassVar

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

BASES = ("compose.yml",)
OVERRIDES = ("compose/*.override.yml", "i18n/*.override.yml")


def _load(path: Path) -> dict:
    return load_yaml_any(str(path), default_if_missing={}) or {}


def _services(path: Path) -> set[str]:
    return set((_load(path).get("services") or {}).keys())


def _defines(path: Path) -> set[str]:
    loaded = _load(path)
    return {
        name
        for name, body in (loaded.get("services") or {}).items()
        if isinstance(body, dict) and ("image" in body or "build" in body)
    }


class TestComposeOverrideServicesDefined(unittest.TestCase):
    root: ClassVar[Path] = Path(PROJECT_ROOT)

    def test_every_extended_service_has_a_definition(self) -> None:
        defined: set[str] = set()
        for base in BASES:
            defined |= _defines(self.root / base)
        for pattern in OVERRIDES:
            for path in sorted(self.root.glob(pattern)):
                defined |= _defines(path)

        orphans: dict[str, set[str]] = {}
        for pattern in OVERRIDES:
            for path in sorted(self.root.glob(pattern)):
                missing = _services(path) - defined
                if missing:
                    orphans[str(path.relative_to(self.root))] = missing

        self.assertEqual(
            orphans,
            {},
            "Override files extend services that no compose file defines with an "
            f"image or build: {orphans}. Define the service where it is extended, "
            "or move the override next to its definition.",
        )


if __name__ == "__main__":
    unittest.main()
