from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import read_text
from utils.roles import lifecycle

_AXIS = (
    "planned",
    "pre-alpha",
    "alpha",
    "beta",
    "rc",
    "stable",
    "deprecated",
    "eol",
)
_UPSTREAM = "infinito-nexus/core"
_MAIN = "refs/heads/main"
_CONTEXTS = {
    "main": {
        "description": "Upstream main.",
        "repository": _UPSTREAM,
        "refs": [_MAIN],
        "events": ["push"],
    },
    "rest": {"description": "Everything else."},
}


def _status(*predecessors: str) -> dict:
    entry: dict = {"description": "One sentence."}
    if predecessors:
        entry["predecessors"] = list(predecessors)
    return entry


def _errors(statuses: dict, contexts: dict | None = None) -> list[str]:
    spec = {"contexts": _CONTEXTS if contexts is None else contexts}
    return lifecycle.parse({**spec, "statuses": statuses})[1]


def _github(**overrides: str) -> dict[str, str]:
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": _UPSTREAM,
        "GITHUB_REF": _MAIN,
        "GITHUB_EVENT_NAME": "push",
    }
    env.update(overrides)
    return env


class TestTheDecidedSets(unittest.TestCase):
    def setUp(self) -> None:
        self.spot = lifecycle.load()

    def test_the_derived_order_is_the_documented_axis(self) -> None:
        self.assertEqual(_AXIS, self.spot.order)

    def test_upstream_main_deploys_beta_rc_stable(self) -> None:
        self.assertEqual("beta rc stable", lifecycle.default_envelope("upstream-main"))

    def test_every_other_run_deploys_alpha_to_deprecated(self) -> None:
        self.assertEqual(
            "alpha beta rc stable deprecated", lifecycle.default_envelope("other")
        )

    def test_the_tested_set_is_the_union_of_the_contexts(self) -> None:
        self.assertEqual(
            {"alpha", "beta", "rc", "stable", "deprecated"},
            lifecycle.tested_lifecycles(),
        )

    def test_image_discovery_and_updaters_skip_only_eol(self) -> None:
        self.assertEqual({"eol"}, self.spot.without_action(lifecycle.IMAGE_MIRROR))
        self.assertEqual({"eol"}, self.spot.without_action(lifecycle.VERSION_UPDATE))

    def test_the_update_check_verdicts(self) -> None:
        self.assertEqual({"eol"}, self.spot.with_action(lifecycle.UPDATE_CHECK_FAIL))
        self.assertEqual(
            {"deprecated"}, self.spot.with_action(lifecycle.UPDATE_CHECK_WARN)
        )

    def test_the_eol_label(self) -> None:
        self.assertEqual({"eol"}, self.spot.with_action(lifecycle.EOL_LABEL))

    def test_the_reference_flags(self) -> None:
        self.assertEqual(
            {"beta", "rc", "stable"}, self.spot.with_flag(lifecycle.PRODUCTION)
        )
        self.assertEqual({"eol"}, self.spot.with_flag(lifecycle.RETIRED))
        self.assertEqual({"deprecated", "eol"}, self.spot.beyond_production())


class TestContextDerivation(unittest.TestCase):
    def _context(self, env: dict[str, str]) -> str:
        with patch.dict(os.environ, env, clear=True):
            return lifecycle.current_context()

    def test_an_upstream_main_push_and_schedule_match(self) -> None:
        self.assertEqual("upstream-main", self._context(_github()))
        self.assertEqual(
            "upstream-main", self._context(_github(GITHUB_EVENT_NAME="schedule"))
        )

    def test_a_fork_main_takes_the_fallback(self) -> None:
        self.assertEqual(
            "other", self._context(_github(GITHUB_REPOSITORY="someone/core"))
        )

    def test_a_pull_request_takes_the_fallback(self) -> None:
        env = _github(GITHUB_REF="refs/pull/7/merge", GITHUB_EVENT_NAME="pull_request")
        self.assertEqual("other", self._context(env))

    def test_another_upstream_branch_takes_the_fallback(self) -> None:
        env = _github(GITHUB_REF="refs/heads/feature/x")
        self.assertEqual("other", self._context(env))

    def test_a_manual_dispatch_on_upstream_main_takes_the_fallback(self) -> None:
        env = _github(GITHUB_EVENT_NAME="workflow_dispatch")
        self.assertEqual("other", self._context(env))

    def test_an_act_run_takes_the_fallback(self) -> None:
        self.assertEqual("other", self._context(_github(ACT="true")))

    def test_a_local_run_takes_the_fallback(self) -> None:
        self.assertEqual("other", self._context({}))


class TestGraphValidation(unittest.TestCase):
    def test_a_chain_is_valid(self) -> None:
        self.assertEqual([], _errors({"a": _status(), "b": _status("a")}))

    def test_a_cycle_is_reported(self) -> None:
        errors = _errors({"a": _status(), "b": _status("a", "c"), "c": _status("b")})
        self.assertTrue(any("cycle" in e for e in errors), errors)

    def test_an_unknown_predecessor_is_reported(self) -> None:
        errors = _errors({"a": _status(), "b": _status("a", "nope")})
        self.assertTrue(any("unknown predecessor 'nope'" in e for e in errors), errors)

    def test_an_unreachable_status_is_reported(self) -> None:
        errors = _errors(
            {"a": _status(), "b": _status("a"), "x": _status("y"), "y": _status("x")}
        )
        self.assertTrue(any("reaches x, y" in e for e in errors), errors)

    def test_a_second_entry_is_reported(self) -> None:
        errors = _errors({"a": _status(), "b": _status()})
        self.assertTrue(any("exactly one entry" in e for e in errors), errors)

    def test_an_ambiguous_order_is_reported(self) -> None:
        errors = _errors({"a": _status(), "b": _status("a"), "c": _status("a")})
        self.assertTrue(any("not unique: b, c" in e for e in errors), errors)

    def test_a_skip_edge_keeps_the_order_unique(self) -> None:
        statuses = {"a": _status(), "b": _status("a"), "c": _status("a", "b")}
        lc, errors = lifecycle.parse({"contexts": _CONTEXTS, "statuses": statuses})
        self.assertEqual([], errors)
        self.assertEqual(("a", "b", "c"), lc.order)

    def test_unknown_names_and_a_missing_description_are_reported(self) -> None:
        errors = _errors(
            {"a": {"flags": ["prod"], "actions": ["deploy"], "colour": "red"}}
        )
        self.assertTrue(any("unknown flag 'prod'" in e for e in errors), errors)
        self.assertTrue(any("unknown action 'deploy'" in e for e in errors), errors)
        self.assertTrue(any("unknown key 'colour'" in e for e in errors), errors)
        self.assertTrue(any("description" in e for e in errors), errors)

    def test_production_and_retired_together_are_reported(self) -> None:
        entry = _status()
        entry["flags"] = [lifecycle.PRODUCTION, lifecycle.RETIRED]
        self.assertTrue(any("both" in e for e in _errors({"a": entry})))


class TestContextValidation(unittest.TestCase):
    def test_an_unknown_ci_deploy_context_is_reported(self) -> None:
        entry = _status()
        entry[lifecycle.CI_DEPLOY] = ["nowhere"]
        errors = _errors({"a": entry})
        self.assertTrue(any("unknown context 'nowhere'" in e for e in errors), errors)

    def test_a_missing_fallback_is_reported(self) -> None:
        errors = _errors({"a": _status()}, {"main": _CONTEXTS["main"]})
        self.assertTrue(any("without criteria" in e for e in errors), errors)

    def test_two_fallbacks_are_reported(self) -> None:
        contexts = {"one": {"description": "x"}, "two": {"description": "y"}}
        errors = _errors({"a": _status()}, contexts)
        self.assertTrue(any("found 2" in e for e in errors), errors)

    def test_partial_criteria_are_reported(self) -> None:
        contexts = {
            "half": {"description": "x", "repository": _UPSTREAM},
            "rest": {"description": "y"},
        }
        errors = _errors({"a": _status()}, contexts)
        self.assertTrue(any("all of" in e for e in errors), errors)


class TestReferenceRule(unittest.TestCase):
    def setUp(self) -> None:
        self.spot = lifecycle.load()

    def test_nobody_may_reference_a_retired_role(self) -> None:
        for consumer in (*_AXIS, None):
            with self.subTest(consumer=consumer):
                self.assertIsNotNone(self.spot.forbidden(consumer, "eol"))

    def test_a_production_role_may_not_reference_a_deprecated_one(self) -> None:
        for consumer in ("beta", "rc", "stable"):
            with self.subTest(consumer=consumer):
                self.assertIsNotNone(self.spot.forbidden(consumer, "deprecated"))

    def test_a_non_production_role_may_reference_a_deprecated_one(self) -> None:
        for consumer in ("planned", "pre-alpha", "alpha", "deprecated", None):
            with self.subTest(consumer=consumer):
                self.assertIsNone(self.spot.forbidden(consumer, "deprecated"))

    def test_a_production_role_may_reference_an_earlier_status(self) -> None:
        self.assertIsNone(self.spot.forbidden("stable", "pre-alpha"))
        self.assertIsNone(self.spot.forbidden("beta", None))


class TestEnvelope(unittest.TestCase):
    def test_the_environment_wins(self) -> None:
        with patch.dict(os.environ, {lifecycle.ENVELOPE_KEY: "eol"}, clear=True):
            self.assertEqual("eol", lifecycle.envelope())

    def test_an_empty_value_falls_to_the_run_context(self) -> None:
        env = {**_github(), lifecycle.ENVELOPE_KEY: " "}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual("beta rc stable", lifecycle.envelope())
        with patch.dict(os.environ, {lifecycle.ENVELOPE_KEY: ""}, clear=True):
            self.assertEqual("alpha beta rc stable deprecated", lifecycle.envelope())

    def test_changing_a_ci_deploy_context_changes_the_derived_envelope(self) -> None:
        text = read_text(str(lifecycle.lifecycle_file()))
        marker = "      - pre-alpha\n    ci-deploy:\n      - other\n"
        self.assertIn(marker, text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = lifecycle.lifecycle_file(root)
            target.parent.mkdir(parents=True)
            target.write_text(text.replace(marker, "      - pre-alpha\n"), "utf-8")
            self.assertEqual(
                "beta rc stable deprecated", lifecycle.default_envelope("other", root)
            )


if __name__ == "__main__":
    unittest.main()
