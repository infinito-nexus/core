"""Integration guard: a mutual pair the clone detection cannot merge must
pin the partner's variant explicitly.

Rationale
---------

Two roles reference each other when each declares
``"{{ '<partner>' in group_names }}"`` for a service key. Each side switches
its key on in some variant, and both of those rounds stand up both stacks.

When the two rounds deploy the same inventory they are clones and the matrix
can collapse them, so nothing has to be declared. When the inventories differ
the collapse cannot happen, and the pairing then rests on the two variant
lists happening to agree on an index: the round hands every role the round
index and clamps to variant 0 for a role with fewer entries
(:func:`utils.roles.applications.variants.services_overrides_for_round`).
Insert a variant on one side and the other side's round silently deploys a
partner configuration that does not reciprocate.

``# variant-pin: <role>#<index|reciprocal>`` on the line above the service
entry states the dependency instead of inheriting it. This guard requires one
wherever the clone detection cannot cover for its absence.

The comparison is between the inventories the two pinning rounds produce. Two
rounds with equal inventories but different indices are left alone here even
though only an equal index makes the collapse safe; that narrower question
belongs to the clone detection itself, not to this guard.

A pair is exempt when either role's ``meta/variants.yml`` carries
``# nocheck: variant-pin-required``.
"""

from __future__ import annotations

import functools
import re
import unittest

from cli.administration.deploy.development.inventory.legacy_resolver import (
    _resolve_round_include,
)
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.variant_pins import pins_of
from utils.roles.applications.variants import services_overrides_for_round
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
_GROUP_MEMBERSHIP = re.compile(r"'([a-z0-9][a-z0-9-]*)'\s+in\s+group_names")
_NOCHECK = re.compile(r"#\s*nocheck:\s*variant-pin-required\b")


@functools.lru_cache(maxsize=1)
def _edges() -> dict[str, dict[str, str]]:
    """role -> {partner role: the service key gating on it}."""
    edges: dict[str, dict[str, str]] = {}
    for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
        services_path = role_dir / ROLE_FILE_META_SERVICES
        if not services_path.is_file():
            continue
        services = load_yaml_any(services_path)
        if not isinstance(services, dict):
            continue
        for key, entry in services.items():
            if not isinstance(entry, dict):
                continue
            match = _GROUP_MEMBERSHIP.search(str(entry.get("enabled", "")))
            if match and match.group(1) != role_dir.name:
                edges.setdefault(role_dir.name, {})[match.group(1)] = str(key)
    return edges


@functools.cache
def _rounds_pinned_true(role: str, key: str) -> tuple[int, ...]:
    path = ROLES_DIR / role / ROLE_FILE_META_VARIANTS
    if not path.is_file():
        return ()
    variants = load_yaml_any(path)
    if not isinstance(variants, list):
        return ()
    return tuple(
        index
        for index, variant in enumerate(variants)
        if isinstance(variant, dict)
        and isinstance((variant.get("services") or {}).get(key), dict)
        and variant["services"][key].get("enabled") is True
    )


@functools.cache
def _closure(role: str, index: int) -> frozenset[str]:
    """The apps one round deploys.

    ``cli.meta.ci.matrix.deployed_rounds`` answers the same question but
    resolves every round of the role; a partner with fourteen variants then
    costs fourteen resolutions to read one.
    """
    overrides = services_overrides_for_round(
        roles_dir=str(ROLES_DIR),
        round_index=index,
        primary_app_variants={role: index},
    )
    return frozenset(
        _resolve_round_include(primary_apps=[role], services_overrides=overrides)
    )


@functools.cache
def _exempt(role: str) -> bool:
    path = ROLES_DIR / role / ROLE_FILE_META_VARIANTS
    if not path.is_file():
        return False
    return bool(_NOCHECK.search(read_text(str(path))))


def _pins_partner(role: str, index: int, partner: str) -> bool:
    return partner in pins_of(role, roles_dir=str(ROLES_DIR)).get(index, {})


def mutual_pairs() -> list[tuple[str, str, str, str]]:
    """(role, its key for partner, partner, partner's key for role) per pair."""
    edges = _edges()
    pairs = []
    for role, partners in sorted(edges.items()):
        for partner, key in sorted(partners.items()):
            if role >= partner:
                continue
            mirror = edges.get(partner, {}).get(role)
            if mirror:
                pairs.append((role, key, partner, mirror))
    return pairs


class TestVariantPinRequired(unittest.TestCase):
    def test_a_pair_the_clone_detection_misses_declares_its_pin(self) -> None:
        findings = []
        for role, key, partner, mirror in mutual_pairs():
            if _exempt(role) or _exempt(partner):
                continue
            here = _rounds_pinned_true(role, key)
            there = _rounds_pinned_true(partner, mirror)
            if not here or not there:
                continue
            if any(
                _closure(role, a) == _closure(partner, b) for a in here for b in there
            ):
                continue
            if any(_pins_partner(role, a, partner) for a in here):
                continue
            if any(_pins_partner(partner, b, role) for b in there):
                continue
            findings.append(
                f"  - {role}.{key} (round(s) {list(here)}) and {partner}.{mirror} "
                f"(round(s) {list(there)}) reference each other, deploy different "
                f"inventories, and neither pins the other"
            )

        self.assertFalse(
            findings,
            f"{len(findings)} mutual pair(s) rely on two variant lists agreeing "
            "on an index, with no clone detection to fall back on:\n"
            + "\n".join(findings)
            + "\n\nAdd '# variant-pin: <partner>#reciprocal' above the service "
            "entry on either side, or '# nocheck: variant-pin-required' with the "
            "reason when the pairing is meant to stay implicit.",
        )

    def test_the_scan_finds_pairs_to_judge(self) -> None:
        """A drifted expression pattern would leave nothing to check."""
        pairs = mutual_pairs()
        self.assertTrue(pairs, "no mutual pair found; the scan reached nothing")
        self.assertTrue(
            [p for p in pairs if _rounds_pinned_true(p[0], p[1])],
            "no mutual pair is pinned true in any variant, so the rule above "
            "can never fire",
        )


if __name__ == "__main__":
    unittest.main()
