from __future__ import annotations

import unittest

from cli.meta.ci.variant_split import compare

from . import edge, entry, record, row, snapshot

HEAVY = [edge("app", "a", "pa"), edge("app", "b", "pb"), edge("pa", "c", "pc")]


def _before() -> dict:
    rows = [row("app#0", 1), row("other#0", 2)]
    rounds = {
        "app#0": record(["pa", "pb", "pc", "app"], HEAVY),
        "other#0": record(["other"], []),
    }
    return snapshot(
        rows,
        rounds,
        head=[entry("app#0"), entry("other#0")],
        jobs=["app#0", "other#0"],
        budget=2,
    )


def _after(*, keep_c: bool = True, budget: int = 3, pin: dict | None = None) -> dict:
    rows = [row("app#0", 1), row("app#3", 2), row("other#0", 3)]
    split = [edge("app", "b", "pb")] + ([edge("pa", "c", "pc")] if keep_c else [])
    rounds = {
        "app#0": record(["pa", "app"], [edge("app", "a", "pa")]),
        "app#3": record(["pa", "pb", "pc", "app"], split, active={"app": 3}),
        "other#0": record(["other"], []),
    }
    tokens = ["app#0", "app#3", "other#0"][:budget]
    return snapshot(
        rows,
        rounds,
        head=[entry(t) for t in tokens],
        jobs=["app#0", "app#3", "other#0"],
        budget=budget,
        pins=[pin] if pin else [],
    )


class TestVerdict(unittest.TestCase):
    def test_a_snapshot_against_itself_keeps_everything(self) -> None:
        self.assertTrue(
            compare.verdict(_before(), _before(), old=["app#0"], split=["app#0"])[
                "kept"
            ]
        )

    def test_a_split_that_carries_every_edge_inside_the_budget_is_kept(self) -> None:
        result = compare.verdict(
            _before(), _after(), old=["app#0"], split=["app#0", "app#3"]
        )
        self.assertEqual(result["edges"]["local"]["keys"], [])
        self.assertTrue(result["kept"], compare.render(result))

    def test_negative_control_a_dep_edge_left_behind_is_reported(self) -> None:
        result = compare.verdict(
            _before(), _after(keep_c=False), old=["app#0"], split=["app#0", "app#3"]
        )
        lost = [("pa", "pc", frozenset({("c", "shared")}))]
        self.assertEqual(result["edges"]["head"]["keys"], lost)
        self.assertEqual(result["invariant"]["edges_lost"], lost)
        self.assertFalse(result["kept"])

    def test_a_row_pushed_past_the_budget_stays_covered(self) -> None:
        result = compare.verdict(
            _before(), _after(budget=2), old=["app#0"], split=["app#0", "app#3"]
        )
        self.assertEqual(result["axes"]["per_sweep"]["0"]["head_lost"], ["other#0"])
        self.assertEqual(result["invariant"]["newly_uncovered"], [])
        self.assertTrue(result["kept"], compare.render(result))

    def test_negative_control_one_false_credit_fails_the_invariant(self) -> None:
        after = _after()
        after["rows"].append(row("lone#0", 4, covered_by=1))
        result = compare.verdict(
            _before(), after, old=["app#0"], split=["app#0", "app#3"]
        )
        self.assertEqual(
            result["invariant"]["introduced_false_credits"],
            ["lone#0: app#0 does not deploy lone"],
        )
        self.assertEqual(result["invariant"]["newly_uncovered"], ["lone#0"])
        self.assertFalse(result["kept"])

    def test_negative_control_a_child_no_job_row_deploys_fails(self) -> None:
        after = _after()
        after["rows"].append({**row("app#5", 5), "clone": True})
        result = compare.verdict(
            _before(), after, old=["app#0"], split=["app#0", "app#3"]
        )
        self.assertEqual(result["invariant"]["newly_uncovered"], ["app#5"])
        self.assertFalse(result["kept"])

    def test_a_credit_to_a_coverer_outside_the_job_list_is_false(self) -> None:
        after = _after()
        after["rows"].append(row("pb#0", 4, covered_by=2))
        after["sweeps"]["0"]["jobs"].remove("app#3")
        result = compare.verdict(
            _before(), after, old=["app#0"], split=["app#0", "app#3"]
        )
        self.assertEqual(
            result["invariant"]["introduced_false_credits"],
            ["pb#0: app#3 is not in the job list"],
        )
        self.assertFalse(result["kept"])

    def test_negative_control_a_new_pin_without_reciprocity_fails(self) -> None:
        pin = {
            "carrier": "app#3",
            "partner": "pa",
            "target": "1",
            "key": "a",
            "reciprocal": "error: no gate",
        }
        result = compare.verdict(
            _before(), _after(pin=pin), old=["app#0"], split=["app#0", "app#3"]
        )
        self.assertEqual(result["pins"]["unreciprocated"], [pin])
        self.assertFalse(result["kept"])

    def test_a_reciprocal_new_pin_passes(self) -> None:
        pin = {
            "carrier": "app#3",
            "partner": "pa",
            "target": "1",
            "key": "a",
            "reciprocal": 1,
        }
        result = compare.verdict(
            _before(), _after(pin=pin), old=["app#0"], split=["app#0", "app#3"]
        )
        self.assertEqual(result["pins"]["unreciprocated"], [])

    def test_the_render_names_the_verdict(self) -> None:
        text = compare.render(
            compare.verdict(
                _before(), _after(keep_c=False), old=["app#0"], split=["app#0", "app#3"]
            )
        )
        self.assertIn("coverage kept: NO", text)


def _gate(
    *,
    jobs: list[str],
    big_include: list[str],
    dark: tuple[str, ...] = (),
    error: str | None = None,
) -> dict:
    rows = [row("big#0", 1), row("dep#0", 2, covered_by=1), row("other#0", 3)]
    rounds = {
        "big#0": record(big_include),
        "dep#0": record(["dep"]),
        "other#0": record(["dep", "big", "other"], dark=dark, error=error),
    }
    return snapshot(rows, rounds, head=[entry(t) for t in jobs], jobs=jobs)


def _gate_verdict(before: dict, after: dict) -> dict:
    return compare.verdict(before, after, old=["big#0"], split=["big#0"])


class TestEachGateAlone(unittest.TestCase):
    def test_a_coverer_leaving_the_job_list_fails_on_the_invariant_alone(self) -> None:
        before = _gate(jobs=["big#0", "other#0"], big_include=["dep", "big"])
        after = _gate(jobs=["other#0"], big_include=["dep", "big"])
        result = _gate_verdict(before, after)
        self.assertEqual(
            result["invariant"]["introduced_false_credits"],
            ["dep#0: big#0 is not in the job list"],
        )
        self.assertEqual(result["coverage"]["introduced"], [])
        self.assertFalse(result["kept"])

    def test_a_coverer_dropping_the_role_fails_on_the_credit_check_alone(self) -> None:
        before = _gate(jobs=["other#0"], big_include=["dep", "big"])
        after = _gate(jobs=["other#0"], big_include=["big"])
        result = _gate_verdict(before, after)
        self.assertEqual(result["invariant"]["introduced_false_credits"], [])
        self.assertEqual(
            result["coverage"]["introduced"], ["dep#0: big#0 does not deploy dep"]
        )
        self.assertFalse(result["kept"])

    def test_a_new_dark_pin_fails_alone(self) -> None:
        before = _gate(jobs=["big#0", "other#0"], big_include=["dep", "big"])
        after = _gate(
            jobs=["big#0", "other#0"],
            big_include=["dep", "big"],
            dark=("other#0 pins dep above k",),
        )
        result = _gate_verdict(before, after)
        self.assertEqual(
            result["pins"]["new_dark_pins"], ["other#0: other#0 pins dep above k"]
        )
        self.assertFalse(result["kept"])

    def test_a_new_round_error_fails_alone(self) -> None:
        before = _gate(jobs=["big#0", "other#0"], big_include=["dep", "big"])
        after = _gate(
            jobs=["big#0", "other#0"], big_include=["dep", "big"], error="pins cycle"
        )
        result = _gate_verdict(before, after)
        self.assertEqual(result["pins"]["new_errors"], ["other#0: pins cycle"])
        self.assertFalse(result["kept"])

    def test_the_gate_fixture_alone_keeps_everything(self) -> None:
        snap = _gate(jobs=["big#0", "other#0"], big_include=["dep", "big"])
        self.assertTrue(_gate_verdict(snap, snap)["kept"])


def _moved(coverer: int) -> dict:
    rows = [
        row("app-a#0", 1),
        row("app-c#0", 3),
        row("app-r#0", 4, covered_by=coverer),
    ]
    rounds = {
        "app-a#0": record(["app-a", "app-r"], active={"app-r": 1}),
        "app-c#0": record(["app-c"]),
        "app-r#0": record(["app-r"]),
    }
    jobs = ["app-a#0", "app-c#0", "app-r#0"]
    return snapshot(rows, rounds, head=[entry(t) for t in jobs], jobs=jobs)


class TestFalseCreditIdentity(unittest.TestCase):
    def test_negative_control_a_false_credit_moved_to_another_coverer_is_new(
        self,
    ) -> None:
        result = compare.verdict(
            _moved(1), _moved(3), old=["app-a#0"], split=["app-a#0"]
        )
        self.assertEqual(
            result["invariant"]["introduced_false_credits"],
            ["app-r#0: app-c#0 does not deploy app-r"],
        )
        self.assertFalse(result["kept"])

    def test_an_unchanged_false_credit_is_not_blamed_on_the_split(self) -> None:
        result = compare.verdict(
            _moved(1), _moved(1), old=["app-a#0"], split=["app-a#0"]
        )
        self.assertEqual(result["invariant"]["introduced_false_credits"], [])
        self.assertTrue(result["kept"])


def _variant(other_edges: list, big_edges: list) -> dict:
    rows = [row("big#0", 1), row("dep#0", 2), row("other#0", 3)]
    rounds = {
        "big#0": record(["dep", "big"], big_edges),
        "dep#0": record(["dep"]),
        "other#0": record(
            ["dep", "big", "other"],
            other_edges,
            active={"dep": other_edges[0][4] if other_edges else 0},
        ),
    }
    jobs = ["other#0", "dep#0"]
    return snapshot(
        rows,
        rounds,
        head=[entry(t) for t in jobs],
        jobs=jobs,
        counts={"dep": 2},
    )


class TestVariantEdges(unittest.TestCase):
    OWN = (edge("big", "k", "dep"),)

    def test_negative_control_a_declared_edge_at_a_lost_variant_pair_fails(
        self,
    ) -> None:
        before = _variant([edge("big", "k", "dep")], list(self.OWN))
        after = _variant([edge("big", "k", "dep", pv=1)], list(self.OWN))
        result = compare.verdict(before, after, old=["other#0"], split=["other#0"])
        self.assertEqual(result["invariant"]["edges_lost"], [])
        self.assertEqual(
            result["invariant"]["variant_edges_lost"],
            [["big", 0, "k", "dep", 0, "shared"]],
        )
        self.assertFalse(result["kept"])

    def test_an_edge_the_consumer_no_longer_declares_is_retired(self) -> None:
        before = _variant([edge("big", "k", "dep")], list(self.OWN))
        after = _variant([], [])
        result = compare.verdict(before, after, old=["other#0"], split=["other#0"])
        self.assertEqual(result["invariant"]["variant_edges_lost"], [])
        self.assertEqual(result["invariant"]["variant_edges_retired"], 1)


class TestEdgeCheckPerRound(unittest.TestCase):
    def test_keys_of_two_old_rounds_are_never_merged_into_one_identity(self) -> None:
        rows = [row("app#0", 1), row("app#1", 2)]
        rounds = {
            "app#0": record(["kc", "app"], [edge("app", "sso", "kc")]),
            "app#1": record(["kc", "app"], [edge("app", "oidc", "kc", cv=1)]),
        }
        snap = snapshot(rows, rounds, head=[], jobs=["app#0", "app#1"])
        result = compare.edge_check(
            snap, snap, old=["app#0", "app#1"], split=["app#0", "app#1"]
        )
        self.assertEqual(result["total"]["keys"], 2)
        self.assertEqual(result["local"]["keys"], [])


if __name__ == "__main__":
    unittest.main()
