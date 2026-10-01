"""Unit tests for `prune_orphans_after_disable` (legacy_resolver).

The graph walk is exercised against a fake `CombinedResolver` so the
cut-node and cross-parent semantics are pinned independently of the
real role topology.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cli.administration.deploy.development.inventory import (
    prune_orphans_after_disable,
)


class _FakeResolver:
    def __init__(self, edges: dict[str, list[str]], **_kwargs: object) -> None:
        self._edges = edges

    def edges_for(self, node: str) -> SimpleNamespace:
        return SimpleNamespace(
            dependencies=[],
            services=self._edges.get(node, []),
            run_after=[],
        )


_GRAPH = {
    "A": ["M", "P"],
    "M": ["K"],
    "P": ["K"],
    "K": ["DB"],
    "N": ["DB"],
}
_RESOLVER_PATH = (
    "cli.meta.roles.applications.resolution.combined.resolver.CombinedResolver"
)


class TestPruneOrphansAfterDisable(unittest.TestCase):
    def _prune(self, include, primaries, disabled):
        with patch(
            _RESOLVER_PATH,
            side_effect=lambda **kw: _FakeResolver(_GRAPH, **kw),
        ):
            return prune_orphans_after_disable(
                include=include,
                primary_apps=primaries,
                disabled_app_ids=disabled,
                services_overrides={},
            )

    def test_sole_root_disable_collapses_subtree(self) -> None:
        kept, pruned = self._prune(
            include=("DB", "K", "M", "P", "A"),
            primaries=["A"],
            disabled={"M", "P"},
        )
        self.assertEqual(kept, ("A",))
        self.assertEqual(sorted(pruned), ["DB", "K"])

    def test_no_disable_is_identity(self) -> None:
        include = ("DB", "K", "M", "P", "A")
        kept, pruned = self._prune(include=include, primaries=["A"], disabled=set())
        self.assertEqual(kept, include)
        self.assertEqual(pruned, ())

    def test_shared_dep_kept_when_another_primary_parents_it(self) -> None:
        kept, pruned = self._prune(
            include=("DB", "K", "M", "P", "A", "N"),
            primaries=["A", "N"],
            disabled={"M"},
        )
        self.assertIn("DB", kept)
        self.assertNotIn("M", kept)
        self.assertEqual(pruned, ())


class TestRoundIncludeIsDispatchable(unittest.TestCase):
    """Every include entry becomes an inventory group and a deploy id.

    `utils.roles.stage` loops a stage only over invokable category paths,
    so a non-invokable prerequisite in the include list is an id nothing
    can dispatch: the round aborts in `validate_application_ids` before
    ansible starts. `user-workstation` reaches its host through the
    service edge instead, which the loader reads from the closure.
    """

    def _include(self, primary: str) -> tuple[str, ...]:
        from cli.administration.deploy.development.inventory.legacy_resolver import (
            _resolve_round_include,
        )

        return _resolve_round_include(primary_apps=[primary], services_overrides={})

    def test_a_desktop_round_carries_the_base_but_not_the_account(self) -> None:
        include = self._include("dsk-gnome")

        self.assertIn("dsk-base", include)
        self.assertNotIn("user-workstation", include)

    def test_a_meta_dependency_that_is_not_invokable_is_dropped(self) -> None:
        include = self._include("dsk-bluray-player")

        self.assertIn("dsk-base", include)
        self.assertNotIn("dev-java", include)

    def test_the_primary_app_is_always_kept(self) -> None:
        self.assertEqual(self._include("dsk-base")[-1], "dsk-base")


if __name__ == "__main__":
    unittest.main()
