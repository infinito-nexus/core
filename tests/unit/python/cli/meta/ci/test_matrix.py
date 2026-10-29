from __future__ import annotations

import unittest
import unittest.mock as mock
from typing import ClassVar

from cli.meta.ci import matrix


def _entry(
    app: str,
    variant: str,
    mode: str,
    *,
    network: str = "clearnet",
    priority: bool = False,
    covered: str = "0",
    clone: bool = False,
) -> dict:
    return {
        "apps": app,
        "variant": variant,
        "mode": mode,
        "network": network,
        "priority": "true" if priority else "false",
        "covered": covered,
        "clone": "true" if clone else "false",
    }


class TestChunksOf(unittest.TestCase):
    def _chunks(self, entries: list[dict], *, size: int) -> list[list[dict]]:
        with (
            mock.patch.object(matrix.slots, "chunk_size", return_value=size),
            mock.patch.object(matrix.slots, "chunk_blocks", return_value=4),
            mock.patch.object(matrix.slots, "available", return_value=99),
        ):
            return matrix.chunks_of(entries, 0)

    def test_a_chunk_is_sorted_by_name_then_variant(self) -> None:
        entries = [
            _entry("web-app-b", "1", "compose"),
            _entry("web-app-a", "1", "compose"),
            _entry("web-app-a", "0", "compose"),
        ]
        chunk = self._chunks(entries, size=9)[0]
        self.assertEqual(
            [(e["apps"], e["variant"]) for e in chunk],
            [("web-app-a", "0"), ("web-app-a", "1"), ("web-app-b", "1")],
        )

    def test_the_split_still_follows_the_discovery_ranking(self) -> None:
        entries = [
            _entry("web-app-z", "0", "compose"),
            _entry("web-app-a", "0", "compose"),
        ]
        chunks = self._chunks(entries, size=1)
        self.assertEqual(
            [chunk[0]["apps"] for chunk in chunks], ["web-app-z", "web-app-a"]
        )

    def test_a_short_priority_chunk_leaves_the_regular_rows_a_spare_block(
        self,
    ) -> None:
        entries = [_entry("web-app-p", "0", "compose", priority=True)] + [
            _entry(f"web-app-{index:02d}", "0", "compose") for index in range(20)
        ]
        with (
            mock.patch.object(matrix.slots, "chunk_size", return_value=10),
            mock.patch.object(matrix.slots, "chunk_count", return_value=2),
            mock.patch.object(matrix.slots, "chunk_blocks", return_value=3),
            mock.patch.object(matrix.slots, "available", return_value=21),
        ):
            chunks = matrix.chunks_of(entries, 0)
        self.assertEqual(
            [len(chunk) for chunk in chunks],
            [1, 10, 10],
            "the split must get every declared block, not only the ones the "
            "budget fills, or the rows a short priority chunk leaves go unplanned",
        )

    def test_priority_chunks_are_sorted_on_their_own(self) -> None:
        entries = [
            _entry("web-app-z", "0", "compose", priority=True),
            _entry("web-app-a", "0", "compose", priority=True),
            _entry("web-app-b", "0", "compose"),
        ]
        chunks = self._chunks(entries, size=9)
        self.assertEqual([e["apps"] for e in chunks[0]], ["web-app-a", "web-app-z"])
        self.assertEqual([e["apps"] for e in chunks[1]], ["web-app-b"])


class TestPriorityChunks(unittest.TestCase):
    def _patched(self, *, size: int, blocks: int = 4):
        return (
            mock.patch.object(matrix.slots, "chunk_size", return_value=size),
            mock.patch.object(matrix.slots, "chunk_blocks", return_value=blocks),
            mock.patch.object(matrix.slots, "available", return_value=99),
        )

    def _count(self, entries: list[dict], *, size: int, blocks: int = 4) -> int:
        chunk_size, chunk_blocks, available = self._patched(size=size, blocks=blocks)
        with chunk_size, chunk_blocks, available:
            return matrix.priority_chunks(entries)

    def _sweep(self, priority: int, regular: int) -> list[dict]:
        return [
            _entry(f"web-app-p{index}", "0", "compose", priority=True)
            for index in range(priority)
        ] + [_entry(f"web-app-r{index}", "0", "compose") for index in range(regular)]

    def test_a_sweep_without_a_priority_line_stars_no_batch(self) -> None:
        self.assertEqual(self._count(self._sweep(0, 5), size=2), 0)

    def test_the_priority_rows_count_the_chunks_they_fill(self) -> None:
        self.assertEqual(self._count(self._sweep(3, 5), size=2), 2)

    def test_the_declared_blocks_cap_the_count(self) -> None:
        self.assertEqual(self._count(self._sweep(5, 0), size=1, blocks=3), 3)

    def test_the_count_splits_the_sweep_at_its_priority_seam(self) -> None:
        entries = self._sweep(3, 5)
        chunk_size, chunk_blocks, available = self._patched(size=2)
        with chunk_size, chunk_blocks, available:
            chunks = matrix.chunks_of(entries, 0)
            count = matrix.priority_chunks(entries)
        self.assertTrue(
            all(e["priority"] == "true" for chunk in chunks[:count] for e in chunk)
        )
        self.assertTrue(
            all(e["priority"] == "false" for chunk in chunks[count:] for e in chunk)
        )


_REGULAR = [
    _entry("web-app-a", "0", "compose"),
    _entry("web-app-b", "1", "swarm", network="tor"),
    _entry("web-app-b", "2", "compose"),
]


class TestRedundant(unittest.TestCase):
    def _chunked(self, entries: list[dict]) -> list[dict]:
        with (
            mock.patch.object(matrix.slots, "chunk_size", return_value=10),
            mock.patch.object(matrix.slots, "chunk_blocks", return_value=4),
            mock.patch.object(matrix.slots, "available", return_value=99),
        ):
            return [row for chunk in matrix.chunks_of(entries, 0) for row in chunk]

    def test_a_covered_row_never_reaches_a_chunk(self) -> None:
        entries = [_entry("web-app-a", "0", "compose", covered="7")]
        self.assertEqual(self._chunked(entries), [])

    def test_a_clone_never_reaches_a_chunk(self) -> None:
        entries = [_entry("web-app-a", "0", "compose", clone=True)]
        self.assertEqual(self._chunked(entries), [])

    def test_a_plain_row_still_reaches_a_chunk(self) -> None:
        entries = [_entry("web-app-a", "0", "compose")]
        self.assertEqual(len(self._chunked(entries)), 1)

    def test_a_pinned_clone_is_kept(self) -> None:
        entries = [_entry("web-app-a", "0", "compose", priority=True, clone=True)]
        self.assertEqual(len(self._chunked(entries)), 1)


class TestOffsetIndex(unittest.TestCase):
    def test_nothing_given_starts_at_the_head(self) -> None:
        for raw in (None, "", 0, "0"):
            with self.subTest(raw=raw):
                self.assertEqual(matrix.offset_index(raw, _REGULAR), 0)

    def test_a_number_is_a_row_count(self) -> None:
        self.assertEqual(matrix.offset_index("2", _REGULAR), 2)

    def test_a_negative_count_reads_as_the_head(self) -> None:
        self.assertEqual(matrix.offset_index("-5", _REGULAR), 0)

    def test_a_role_token_starts_at_its_first_row(self) -> None:
        self.assertEqual(matrix.offset_index("web-app-b", _REGULAR), 1)

    def test_a_pinned_variant_starts_at_that_variant(self) -> None:
        self.assertEqual(matrix.offset_index("web-app-b#2", _REGULAR), 2)

    def test_a_pinned_mode_picks_the_row_of_that_mode(self) -> None:
        self.assertEqual(matrix.offset_index("web-app-b#1@swarm", _REGULAR), 1)

    def test_a_pinned_network_mode_picks_the_row_of_that_network_mode(self) -> None:
        self.assertEqual(matrix.offset_index("web-app-b+tor", _REGULAR), 1)
        self.assertEqual(matrix.offset_index("web-app-b+clearnet", _REGULAR), 2)
        with self.assertRaises(SystemExit):
            matrix.offset_index("web-app-b+multi", _REGULAR)

    def test_a_token_naming_no_regular_row_aborts(self) -> None:
        with self.assertRaises(SystemExit):
            matrix.offset_index("web-app-gone#3", _REGULAR)


def _row(app: str, variant: int) -> dict:
    return {"name": app, "variant": variant, "test_compose": True}


class TestCandidates(unittest.TestCase):
    _DISCOVERED: ClassVar[list] = [
        _row("web-app-a", 0),
        _row("web-app-b", 0),
        _row("web-app-b", 1),
    ]

    def _candidates(self, priority: str) -> list[dict]:
        with mock.patch.object(
            matrix.query, "discover_rows", return_value=list(self._DISCOVERED)
        ):
            return matrix.candidates(
                modes=("compose",), whitelist="", priority=priority, lifecycles=""
            )

    def _regular(self, priority: str) -> set[tuple[str, int]]:
        return {
            (row["name"], row["variant"])
            for row in self._candidates(priority)
            if not row["priority"]
        }

    def test_a_pinned_variant_leaves_its_siblings_in_the_regular_line(self) -> None:
        self.assertEqual(
            self._regular("web-app-b#0"), {("web-app-a", 0), ("web-app-b", 1)}
        )

    def test_a_pinned_variant_does_not_come_back_as_a_regular_row(self) -> None:
        self.assertNotIn(("web-app-b", 0), self._regular("web-app-b#0"))

    def test_a_bare_token_withdraws_the_whole_role(self) -> None:
        with mock.patch.object(
            matrix.query, "discover_rows", return_value=list(self._DISCOVERED)
        ) as discovered:
            matrix.candidates(
                modes=("compose",), whitelist="", priority="web-app-b", lifecycles=""
            )
        self.assertEqual(discovered.call_args.kwargs["blacklist"], "web-app-b")

    def test_the_priority_line_alone_runs_only_its_own_query(self) -> None:
        with mock.patch.object(
            matrix.query, "discover_rows", return_value=list(self._DISCOVERED)
        ) as discovered:
            rows = matrix.priority_candidates(
                modes=("compose",), priority="web-app-b#1", lifecycles=""
            )
        discovered.assert_called_once()
        self.assertEqual(
            [(row["name"], row["variant"], row["priority"]) for row in rows],
            [("web-app-b", 1, True)],
        )
        self.assertEqual(rows[0]["modes"], ("compose",))

    def test_an_empty_priority_line_queries_nothing(self) -> None:
        with mock.patch.object(matrix.query, "discover_rows") as discovered:
            rows = matrix.priority_candidates(
                modes=("compose",), priority="", lifecycles=""
            )
        self.assertEqual(rows, [])
        discovered.assert_not_called()


class TestWithDeployedServices(unittest.TestCase):
    def setUp(self) -> None:
        matrix.deployed_rounds.cache_clear()
        self.addCleanup(matrix.deployed_rounds.cache_clear)

    def test_each_variant_takes_the_apps_its_own_round_deploys(self) -> None:
        plan = [
            (0, "plan-0", {}, ("web-app-a", "svc-db-postgres"), ()),
            (1, "plan-1", {}, ("web-app-a", "svc-ai-lmstudio"), ()),
        ]
        with mock.patch.object(
            matrix, "plan_dev_inventory_matrix", return_value=plan
        ) as planner:
            rows = [
                matrix.with_deployed_services(
                    {"name": "web-app-a", "variant": variant, "services": ["x"]}
                )
                for variant in (0, 1)
            ]

        self.assertEqual(
            [row["services"] for row in rows],
            [("web-app-a", "svc-db-postgres"), ("web-app-a", "svc-ai-lmstudio")],
        )
        planner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
