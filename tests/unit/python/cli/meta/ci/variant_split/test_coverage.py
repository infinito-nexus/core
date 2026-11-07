from __future__ import annotations

import unittest

from cli.meta.ci.variant_split.coverage import children, credit_findings, declared
from cli.meta.ci.variant_split.edges import Edge

from . import edge, record, row, snapshot


def _snap(coverer_round: dict) -> dict:
    rows = [row("big#0", 1), row("dep#0", 2, covered_by=1)]
    rounds = {
        "big#0": coverer_round,
        "dep#0": record(["db", "dep"], [edge("dep", "db", "db")]),
    }
    return snapshot(rows, rounds, head=[], jobs=["big#0"])


HONOURED = record(
    ["db", "dep", "big"], [edge("dep", "db", "db"), edge("big", "dep", "dep")]
)


class TestCreditFindings(unittest.TestCase):
    def test_an_unchanged_honoured_credit_has_no_finding(self) -> None:
        found = credit_findings(_snap(HONOURED), _snap(HONOURED))
        self.assertEqual(
            found["introduced"] + found["thinner"] + found["preexisting"], []
        )

    def test_negative_control_a_coverer_that_drops_the_role_is_a_false_credit(
        self,
    ) -> None:
        after = _snap(record(["big"], []))
        found = credit_findings(_snap(HONOURED), after)
        self.assertEqual(found["introduced"], ["dep#0: big#0 does not deploy dep"])

    def test_negative_control_a_pin_that_moves_the_role_off_variant_0_is_caught(
        self,
    ) -> None:
        pinned = record(
            ["db", "dep", "big"], [edge("dep", "db", "db", cv=2)], active={"dep": 2}
        )
        found = credit_findings(_snap(HONOURED), _snap(pinned))
        self.assertEqual(
            found["introduced"], ["dep#0: big#0 runs dep#2, not the credited #0"]
        )

    def test_negative_control_a_coverer_that_switches_a_key_off_thins_the_credit(
        self,
    ) -> None:
        lean = record(["db", "dep", "big"], [edge("big", "dep", "dep")])
        found = credit_findings(_snap(HONOURED), _snap(lean))
        self.assertEqual(len(found["thinner"]), 1)
        self.assertIn("db", found["thinner"][0])

    def test_a_credit_that_was_already_false_stays_pre_existing(self) -> None:
        broken = _snap(record(["big"], []))
        found = credit_findings(broken, broken)
        self.assertEqual(found["introduced"], [])
        self.assertEqual(len(found["preexisting"]), 1)

    def test_negative_control_a_credit_broken_another_way_is_introduced(self) -> None:
        dropped = _snap(record(["big"], []))
        pinned = _snap(record(["db", "dep", "big"], [], active={"dep": 2}))
        found = credit_findings(dropped, pinned)
        self.assertEqual(found["preexisting"], [])
        self.assertEqual(
            found["introduced"], ["dep#0: big#0 runs dep#2, not the credited #0"]
        )

    def test_negative_control_a_coverer_that_dictates_the_roles_config_is_false(
        self,
    ) -> None:
        dictated = record(
            ["db", "dep", "big"], list(HONOURED["edges"]), dictated={"dep": "big#0"}
        )
        found = credit_findings(_snap(HONOURED), _snap(dictated))
        self.assertEqual(
            found["introduced"], ["dep#0: big#0 dictates the config of dep in big#0"]
        )

    def test_a_dictated_member_does_not_cover_its_child(self) -> None:
        dictated = record(["db", "dep", "big"], dictated={"dep": "big#0"})
        self.assertIn("dep#0", children(_snap(dictated))["uncovered"])

    def test_a_row_that_starts_running_itself_is_reported(self) -> None:
        after = _snap(HONOURED)
        after["rows"][1]["covered_by"] = 0
        self.assertEqual(
            credit_findings(_snap(HONOURED), after)["newly_uncovered"], ["dep#0"]
        )


class TestDeclared(unittest.TestCase):
    EDGE = Edge("ghost", 1, "db", "db", 0, "shared")

    def test_negative_control_an_edge_without_its_row_still_counts_as_declared(
        self,
    ) -> None:
        snap = {"rounds": {}, "variant_counts": {"ghost": 2}}
        self.assertTrue(declared(snap, self.EDGE))

    def test_an_edge_of_a_variant_the_role_no_longer_has_is_retired(self) -> None:
        snap = {"rounds": {}, "variant_counts": {"ghost": 1}}
        self.assertFalse(declared(snap, self.EDGE))


if __name__ == "__main__":
    unittest.main()
