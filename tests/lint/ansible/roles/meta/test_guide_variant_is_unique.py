"""Lint guard: an invokable role declares the guide host in exactly one variant.

The README replay rides on the variant whose ``services.docs.enabled`` is on,
and :mod:`utils.github.variant.instructions` reads that declaration rather than
computing it. Two variants declaring it would hand the same role two replay
rows, which replays the same README block twice and bills the guide host's
deploy twice; none declaring it drops the role out of the instructions test
without anything going red, because the job title carries no marker.

``web-app-docs`` is exempt: the guide host does not consume itself, and its own
``docs`` entry is the provider side of the edge.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):
``# nocheck: guide-variant-unique`` in the role's ``meta/variants.yml``.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

import yaml

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.guide import GUIDE_SERVICE_KEY
from utils.roles.mapping import ROLE_FILE_META_VARIANTS
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
GUIDE_ROLE = "web-app-docs"
_RULE = "guide-variant-unique"


def _variants(path: Path) -> list[Any] | None:
    if not path.is_file():
        return None
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    try:
        loaded = load_yaml_str(text)
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, list) else None


def _suppressed(path: Path) -> bool:
    if not path.is_file():
        return False
    return any(line_has_rule(line, _RULE) for line in read_text(str(path)).splitlines())


def _declaring(variants: list[Any]) -> list[int]:
    return [
        index
        for index, variant in enumerate(variants)
        if isinstance(variant, dict)
        and isinstance(variant.get("services"), dict)
        and isinstance(variant["services"].get(GUIDE_SERVICE_KEY), dict)
        and variant["services"][GUIDE_SERVICE_KEY].get("enabled")
    ]


def offenders() -> list[str]:
    paths = _get_invokable_paths()
    found: list[str] = []
    for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
        role = role_dir.name
        if role == GUIDE_ROLE or not _is_role_invokable(role, paths):
            continue
        path = role_dir / ROLE_FILE_META_VARIANTS
        if _suppressed(path):
            continue
        variants = _variants(path)
        if variants is None:
            found.append(f"{role}: no {ROLE_FILE_META_VARIANTS} declaring the guide")
            continue
        declaring = _declaring(variants)
        if len(declaring) != 1:
            found.append(
                f"{role}: {len(declaring)} variant(s) declare "
                f"services.{GUIDE_SERVICE_KEY}.enabled {declaring}, expected exactly 1"
            )
    return found


class TestGuideVariantIsUnique(unittest.TestCase):
    def test_every_invokable_role_declares_the_guide_once(self) -> None:
        found = offenders()
        self.assertEqual(
            [],
            found,
            f"{len(found)} role(s) do not declare the guide host in exactly one "
            "variant. The replay rides that variant, so two declarations replay "
            "the same README twice and none drops the role from the instructions "
            f"test silently:\n" + "\n".join(f"  - {entry}" for entry in found),
        )


if __name__ == "__main__":
    unittest.main()
