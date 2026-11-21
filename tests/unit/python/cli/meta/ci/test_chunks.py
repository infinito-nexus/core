from __future__ import annotations

import unittest

from cli.meta.ci import chunks


class TestSliceChunks(unittest.TestCase):
    def test_rows_are_cut_into_consecutive_blocks(self) -> None:
        self.assertEqual(chunks.slice_chunks([0, 1, 2, 3, 4], 2), [[0, 1], [2, 3], [4]])

    def test_an_empty_list_yields_no_block(self) -> None:
        self.assertEqual(chunks.slice_chunks([], 3), [])

    def test_a_zero_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            chunks.slice_chunks([1], 0)


class TestOffset(unittest.TestCase):
    def test_the_head_leads_when_no_offset_is_asked_for(self) -> None:
        plan = chunks.plan([], list(range(256)), size=80, blocks=2, budget=256)
        self.assertEqual(plan[0][0], 0)

    def test_an_offset_moves_the_window_by_exactly_that_many_rows(self) -> None:
        plan = chunks.plan(
            [], list(range(256)), size=80, blocks=2, budget=256, offset=5
        )
        self.assertEqual(plan[0][0], 5)

    def test_an_offset_past_the_tail_yields_nothing_instead_of_wrapping(self) -> None:
        plan = chunks.plan(
            [], list(range(10)), size=80, blocks=2, budget=256, offset=99
        )
        self.assertEqual(plan, [])

    def test_a_negative_offset_reads_as_the_head(self) -> None:
        plan = chunks.plan(
            [], list(range(20)), size=80, blocks=2, budget=256, offset=-3
        )
        self.assertEqual(plan[0][0], 0)


class TestPlan(unittest.TestCase):
    def test_priority_gets_its_own_short_chunk(self) -> None:
        plan = chunks.plan(
            list(range(5)),
            list(range(100, 300)),
            size=80,
            blocks=3,
            budget=211,
        )
        self.assertEqual([len(c) for c in plan], [5, 80, 80])
        self.assertEqual(plan[0], list(range(5)))

    def test_a_spare_block_spends_what_a_short_priority_chunk_leaves(self) -> None:
        plan = chunks.plan(
            list(range(9)), list(range(100, 400)), size=80, blocks=4, budget=210
        )
        self.assertEqual([len(c) for c in plan], [9, 80, 80, 41])

    def test_the_seam_chunk_is_never_topped_up_with_regular_rows(self) -> None:
        plan = chunks.plan(
            list(range(5)),
            list(range(100, 300)),
            size=80,
            blocks=3,
            budget=211,
        )
        self.assertTrue(all(row < 5 for row in plan[0]))

    def test_without_priority_the_first_chunk_is_regular(self) -> None:
        plan = chunks.plan([], list(range(200)), size=80, blocks=3, budget=211)
        self.assertEqual([len(c) for c in plan], [80, 80, 40])

    def test_the_block_count_bounds_the_sweep(self) -> None:
        plan = chunks.plan([], list(range(500)), size=80, blocks=2, budget=500)
        self.assertEqual(len(plan), 2)

    def test_the_job_budget_bounds_the_sweep(self) -> None:
        plan = chunks.plan([], list(range(500)), size=80, blocks=3, budget=100)
        self.assertEqual(sum(len(c) for c in plan), 100)

    def test_priority_alone_may_fill_every_block(self) -> None:
        plan = chunks.plan(
            list(range(300)), list(range(50)), size=80, blocks=3, budget=300
        )
        self.assertEqual([len(c) for c in plan], [80, 80, 80])

    def test_priority_is_never_moved_by_the_offset(self) -> None:
        plan = chunks.plan(
            list(range(5)),
            list(range(100, 300)),
            size=80,
            blocks=3,
            budget=211,
            offset=40,
        )
        self.assertEqual(plan[0], list(range(5)))

    def test_an_empty_selection_yields_no_chunk(self) -> None:
        self.assertEqual(chunks.plan([], [], size=80, blocks=3, budget=211), [])


class TestUnlimitedBudget(unittest.TestCase):
    def test_every_row_is_planned(self) -> None:
        plan = chunks.plan(
            list(range(5)), list(range(100, 331)), size=80, blocks=4, budget=None
        )
        self.assertEqual([len(c) for c in plan], [5, 80, 80, 71])
        self.assertEqual(
            [row for chunk in plan for row in chunk],
            list(range(5)) + list(range(100, 331)),
        )

    def test_rows_a_budget_would_cut_are_planned(self) -> None:
        capped = chunks.plan([], list(range(231)), size=80, blocks=4, budget=205)
        unlimited = chunks.plan([], list(range(231)), size=80, blocks=4, budget=None)
        self.assertEqual(sum(len(c) for c in capped), 205)
        self.assertEqual(sum(len(c) for c in unlimited), 231)

    def test_no_chunk_exceeds_its_size(self) -> None:
        plan = chunks.plan([], list(range(600)), size=256, blocks=3, budget=None)
        self.assertEqual([len(c) for c in plan], [256, 256, 88])

    def test_the_offset_still_moves_the_start(self) -> None:
        plan = chunks.plan(
            [], list(range(300)), size=80, blocks=4, budget=None, offset=50
        )
        self.assertEqual(plan[0][0], 50)
        self.assertEqual(sum(len(c) for c in plan), 250)

    def test_an_offset_past_the_tail_leaves_only_priority(self) -> None:
        plan = chunks.plan(
            list(range(3)), list(range(10)), size=80, blocks=4, budget=None, offset=99
        )
        self.assertEqual(plan, [[0, 1, 2]])

    def test_too_few_blocks_fail_naming_the_blocks_needed(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            chunks.plan(
                list(range(5)), list(range(320)), size=80, blocks=4, budget=None
            )
        self.assertIn("needs 5 chunk blocks", str(raised.exception))
        self.assertIn("INFINITO_CI_MAX_CHUNKS=5", str(raised.exception))

    def test_priority_beyond_the_blocks_fails_instead_of_being_cut(self) -> None:
        with self.assertRaises(SystemExit):
            chunks.plan(list(range(300)), [], size=80, blocks=3, budget=None)

    def test_an_empty_selection_yields_no_chunk(self) -> None:
        self.assertEqual(chunks.plan([], [], size=80, blocks=3, budget=None), [])


class TestChunkBeyondTheBudget(unittest.TestCase):
    def test_the_whole_budget_goes_into_one_regular_chunk(self) -> None:
        plan = chunks.plan([], list(range(500)), size=2000, blocks=4, budget=203)
        self.assertEqual([len(c) for c in plan], [203])

    def test_a_short_priority_chunk_strands_no_row_of_the_budget(self) -> None:
        plan = chunks.plan(
            list(range(7)), list(range(100, 600)), size=2000, blocks=4, budget=203
        )
        self.assertEqual([len(c) for c in plan], [7, 196])
        self.assertEqual(plan[0], list(range(7)))

    def test_priority_beyond_the_budget_fills_one_chunk_up_to_the_cap(self) -> None:
        plan = chunks.plan(
            list(range(300)), list(range(50)), size=2000, blocks=4, budget=203
        )
        self.assertEqual([len(c) for c in plan], [203])


if __name__ == "__main__":
    unittest.main()
