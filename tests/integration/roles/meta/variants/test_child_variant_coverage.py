"""Integration guard: splitting a role over more variants never loses a child
variant combination.

A long matrix row is shortened by pinning its children to light variants and
moving the full-weight children into appended parent variants. That is
lossless only while every ``(child, child variant)`` pair a role deployed
before is still deployed by at least one of the role's variants. The guard
settles every round the matrix plans (each role as the only primary, in each
of its variants), collects per role the pairs its rounds deploy, and requires
the recorded baseline to be a subset of today's set. New pairs pass.

Refresh the baseline only to record added coverage::

    python -m tests.integration.roles.meta.variants.test_child_variant_coverage --write-baseline
"""

from __future__ import annotations

import functools
import json
import sys
import unittest
from typing import TYPE_CHECKING

from utils.cache.applications import get_variants
from utils.cache.files import read_text
from utils.roles.applications.variants import resolve_round

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Mapping

ROLES_DIR = str(PROJECT_ROOT / "roles")
BASELINE = (
    PROJECT_ROOT / "tests/integration/roles/meta/variants/child_variant_coverage.json"
)


def coverage(roles_dir: str) -> dict[str, set[str]]:
    """Map role -> the ``child#variant`` pairs its rounds deploy.

    Args:
        roles_dir: the roles tree.

    Returns:
        One set per role, unioned over every variant of that role.
    """
    variants = get_variants(roles_dir=roles_dir, readonly=True)
    found: dict[str, set[str]] = {}
    for app, variant_list in sorted(variants.items()):
        pairs = found.setdefault(app, set())
        for index in range(len(variant_list)):
            resolved = resolve_round(
                roles_dir=roles_dir,
                round_index=index,
                primary_app_variants={app: index},
                variants_per_app=variants,
            )
            pairs.update(
                f"{child}#{resolved.active_index[child]}"
                for child in resolved.include
                if child != app and child in resolved.active_index
            )
    return found


def lost(
    baseline: Mapping[str, list[str]], current: Mapping[str, set[str]]
) -> dict[str, list[str]]:
    """The baseline pairs no variant of the role deploys any more.

    Args:
        baseline: role -> recorded ``child#variant`` pairs.
        current: role -> pairs the roles tree deploys today.
    """
    missing: dict[str, list[str]] = {}
    for role, pairs in sorted(baseline.items()):
        gone = sorted(set(pairs) - current.get(role, set()))
        if gone:
            missing[role] = gone
    return missing


@functools.cache
def _repo_coverage() -> dict[str, set[str]]:
    return coverage(ROLES_DIR)


class TestChildVariantCoverage(unittest.TestCase):
    def test_no_child_variant_pair_is_lost(self) -> None:
        baseline = json.loads(read_text(str(BASELINE)))
        missing = lost(baseline, _repo_coverage())
        if missing:
            self.fail(
                f"{len(missing)} role(s) no longer deploy a child variant pair "
                "they deployed before:\n"
                + "\n".join(
                    f"  - {role}: {', '.join(pairs)}" for role, pairs in missing.items()
                )
                + "\n\nPin the child to that variant in one of the role's "
                "variants, or append a variant that carries it."
            )


class TestChildVariantCoverageControls(unittest.TestCase):
    def test_a_dropped_pair_is_reported(self) -> None:
        self.assertEqual(
            lost({"web-app-a": ["svc-b#0", "svc-c#1"]}, {"web-app-a": {"svc-b#0"}}),
            {"web-app-a": ["svc-c#1"]},
        )

    def test_a_dropped_role_is_reported(self) -> None:
        self.assertEqual(
            lost({"web-app-a": ["svc-b#0"]}, {}),
            {"web-app-a": ["svc-b#0"]},
        )

    def test_added_pairs_pass(self) -> None:
        self.assertEqual(
            lost(
                {"web-app-a": ["svc-b#0"]},
                {"web-app-a": {"svc-b#0", "svc-b#1"}, "web-app-d": {"svc-b#0"}},
            ),
            {},
        )


if __name__ == "__main__":
    if sys.argv[1:] == ["--write-baseline"]:
        BASELINE.write_text(
            json.dumps(
                {role: sorted(pairs) for role, pairs in _repo_coverage().items()},
                indent=1,
                sort_keys=True,
            )
            + "\n"
        )
    else:
        unittest.main()
