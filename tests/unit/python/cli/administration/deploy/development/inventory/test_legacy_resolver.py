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


if __name__ == "__main__":
    unittest.main()
