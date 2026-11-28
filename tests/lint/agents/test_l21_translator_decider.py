"""L21: the translator reads no per-language engine. meta/languages.yml holds
only name, native and direction per language, so which engine answers a
language stays the router's decision; and exactly one infinito_decider
implementation exists under roles/, so there is no second sampler or history."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from tests.lint.agents import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

if TYPE_CHECKING:
    from pathlib import Path

LANGUAGES = PROJECT_ROOT / "meta" / "languages.yml"
ROLES = PROJECT_ROOT / "roles"
ALLOWED_LANGUAGE_KEYS = {"name", "native", "direction"}


def language_offenders(languages: dict) -> list[str]:
    """Return the language entries that carry a key beyond name, native and
    direction (an engine, sampler or history key would let the translator pick
    an engine per language).

    Args:
        languages: the parsed meta/languages.yml mapping.
    """
    out: list[str] = []
    for code, entry in sorted(languages.items()):
        if not isinstance(entry, dict):
            out.append(f"{code}: not a mapping")
            continue
        extra = set(entry) - ALLOWED_LANGUAGE_KEYS
        if extra:
            out.append(
                f"{code}: carries {sorted(extra)} beyond {sorted(ALLOWED_LANGUAGE_KEYS)}"
            )
    return out


def decider_implementations(roles_dir: Path) -> list[Path]:
    """Return every infinito_decider package shipped by a role."""
    if not roles_dir.is_dir():
        return []
    found = roles_dir.rglob("infinito_decider")  # nocheck: project-walk
    return sorted(p for p in found if p.is_dir())


class TestL21(unittest.TestCase):
    def test_languages_hold_no_engine(self):
        languages = load_yaml_any(str(LANGUAGES), default_if_missing={})
        self.assertEqual(language_offenders(languages), [])

    def test_exactly_one_decider(self):
        self.assertEqual(len(decider_implementations(ROLES)), 1)

    def test_red_fixture_fails(self):
        fixture = {
            "xx": {"name": "X", "native": "X", "direction": "ltr", "engine": "deepl"}
        }
        self.assertNotEqual(language_offenders(fixture), [])


if __name__ == "__main__":
    unittest.main()
