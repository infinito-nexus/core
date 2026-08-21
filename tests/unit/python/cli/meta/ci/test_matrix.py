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
    priority: bool = False,
    covered: str = "0",
    clone: bool = False,
) -> dict:
    return {
        "apps": app,
        "variant": variant,
        "mode": mode,
        "tor": "false",
        "priority": "true" if priority else "false",
        "covered": covered,
        "clone": "true" if clone else "false",
    }


class TestChunksOf(unittest.TestCase):
    def _chunks(self, entries: list[dict], *, size: int) -> list[list[dict]]:
        with (
            mock.patch.object(matrix.slots, "chunk_size", return_value=size),
            mock.patch.object(matrix.slots, "chunk_count", return_value=4),
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

    def test_priority_chunks_are_sorted_on_their_own(self) -> None:
        entries = [
            _entry("web-app-z", "0", "compose", priority=True),
            _entry("web-app-a", "0", "compose", priority=True),
            _entry("web-app-b", "0", "compose"),
        ]
        chunks = self._chunks(entries, size=9)
        self.assertEqual([e["apps"] for e in chunks[0]], ["web-app-a", "web-app-z"])
        self.assertEqual([e["apps"] for e in chunks[1]], ["web-app-b"])


_REGULAR = [
    _entry("web-app-a", "0", "compose"),
    _entry("web-app-b", "1", "swarm"),
    _entry("web-app-b", "2", "compose"),
]


class TestRedundant(unittest.TestCase):
    def _chunked(self, entries: list[dict]) -> list[dict]:
        with (
            mock.patch.object(matrix.slots, "chunk_size", return_value=10),
            mock.patch.object(matrix.slots, "chunk_count", return_value=4),
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


if __name__ == "__main__":
    unittest.main()
