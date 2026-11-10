"""Lint: every ``INFINITO_LIFECYCLES`` token names a real lifecycle stage.

``INFINITO_LIFECYCLES`` in ``default.env`` is the envelope the CI test-deploy
discovery exercises (``scripts/meta/resolve/apps.sh --lifecycles``). A token
that matches no stage matches no role, and nothing says so: discovery just
returns a shorter list. Measured on this repository, the envelope read
``alpha beta rc stable maintained`` while the stage
(``docs/contributing/design/role/services/lifecycle.md``) is ``maintenance``.
No role sits at that stage today, so the typo cost nothing - and the first
promotion to it would have dropped silently out of the tested envelope, with a
green pipeline and an untested role.

The valid set is not restated here. It is ``ALLOWED_LIFECYCLES`` from
``tests.lint.ansible.roles.meta.test_layout``, the same set that lint holds
every role's ``meta/services.yml.<entity>.lifecycle`` to, so a stage added
there reaches this rule in the same commit.

The envelope is split the way the Python consumer splits it:
``utils.roles.lifecycle.tested_lifecycles`` calls ``str.split``, so whitespace
is the only separator. A comma is NOT one, which is the whole point of reading
it this way: ``alpha,beta`` reaches ``tested_lifecycles`` as a single token that
matches no stage, while ``cli.meta.roles.applications.complexity.cli``'s
``parse_lifecycles`` splits the ``--lifecycles`` argv on ``[,\\s]+`` and accepts
it. Splitting on commas here would pass exactly the silent drop this rule
exists to report. Tokens are lowercased the way ``parse_lifecycles`` lowercases
them, and :meth:`test_the_lint_and_its_consumer_read_the_same_envelope` asserts
the derived set against ``tested_lifecycles()`` itself, so the two can never
drift apart unnoticed - a capitalised stage that the argv path accepts and the
Python path does not is reported as that disagreement rather than as an unknown
stage.

Only the tracked ``default.env`` is read. The generated ``.env`` is a local
artefact a targeted test run can rewrite, so it is not evidence about the
repository; after changing the value here, ``make dotenv-force`` is what
refreshes it (plain ``make dotenv`` keeps the stale one).

No suppression marker exists: a token outside the axis is a typo, never a
decision.
"""

from __future__ import annotations

import unittest

from tests.lint.ansible.roles.meta.test_layout import ALLOWED_LIFECYCLES
from utils.env.parser import parse_static_env
from utils.roles import lifecycle

from . import PROJECT_ROOT

_KEY = "INFINITO_LIFECYCLES"

_TESTED_STAGES = frozenset({"alpha", "beta", "rc", "stable", "maintenance"})
_UNTESTED_STAGES = frozenset(ALLOWED_LIFECYCLES) - _TESTED_STAGES


def envelope_tokens(raw: str) -> list[str]:
    """Split the envelope value the way ``tested_lifecycles`` consumes it.

    Args:
        raw: the ``INFINITO_LIFECYCLES`` value.

    Returns:
        The whitespace-separated tokens, lowercased, in declaration order. A
        comma stays part of its token: the consumer splits on whitespace only,
        so ``alpha,beta`` is one token that matches no stage, and reading it as
        two would hide that.
    """
    return [token.lower() for token in raw.split()]


class TestLifecycleEnvelopeTokens(unittest.TestCase):
    def test_every_envelope_token_is_a_lifecycle_stage(self) -> None:
        env = parse_static_env(PROJECT_ROOT / "default.env")
        self.assertIn(
            _KEY,
            env,
            f"default.env declares no {_KEY}; the CI test-deploy discovery "
            f"reads it to decide which roles have a row at all.",
        )

        tokens = envelope_tokens(env[_KEY])
        self.assertTrue(
            tokens,
            f"default.env sets {_KEY} to an empty envelope, which "
            f"matches no role at all.",
        )

        unknown = sorted({t for t in tokens if t not in ALLOWED_LIFECYCLES})
        self.assertEqual(
            unknown,
            [],
            f"Every token in {_KEY} MUST name a lifecycle stage, or it "
            f"silently matches no role and the stage drops out of the tested "
            f"envelope with a green pipeline. Known stages: "
            f"{', '.join(sorted(ALLOWED_LIFECYCLES))}. Fix default.env and run "
            f"`make dotenv-force` so the generated .env follows. Unknown:\n  "
            + "\n  ".join(unknown),
        )

    def test_the_lint_and_its_consumer_read_the_same_envelope(self) -> None:
        env = parse_static_env(PROJECT_ROOT / "default.env")
        self.assertIn(
            _KEY,
            env,
            f"default.env declares no {_KEY}; the CI test-deploy discovery "
            f"reads it to decide which roles have a row at all.",
        )
        derived = sorted(set(envelope_tokens(env[_KEY])))
        consumed = sorted(lifecycle.tested_lifecycles())
        self.assertEqual(
            derived,
            consumed,
            f"The envelope this rule judges MUST be the one the consumer "
            f"reads, or the rule can pass on a value that drops stages "
            f"silently. utils.roles.lifecycle.tested_lifecycles() splits "
            f"{_KEY} on whitespace and does not lowercase it, so any value "
            f"these two read differently - a comma, a capital letter - is a "
            f"stage the argv path "
            f"(cli.meta.roles.applications.complexity.cli.parse_lifecycles) "
            f"accepts while every Python consumer of the envelope matches no "
            f"role with it. Fix default.env:\n  "
            f"this rule reads {derived}\n  consumer reads {consumed}",
        )

    def test_the_untested_stages_stay_out_of_the_envelope(self) -> None:
        env = parse_static_env(PROJECT_ROOT / "default.env")
        self.assertIn(
            _KEY,
            env,
            f"default.env declares no {_KEY}; the CI test-deploy discovery "
            f"reads it to decide which roles have a row at all.",
        )

        admitted = sorted(set(envelope_tokens(env[_KEY])) & _UNTESTED_STAGES)
        self.assertEqual(
            admitted,
            [],
            f"{_KEY} MUST NOT admit a stage the lifecycle policy puts outside "
            f"the tested envelope. The eol rules rest on this: an end-of-life "
            f"role stays out of every default CI round, which is why its "
            f"consumers may store a literal false and ship no live "
            f"integration. Admitting one here makes that rationale false "
            f"while every other check stays green. Outside the envelope: "
            f"{', '.join(sorted(_UNTESTED_STAGES))}. Admitted:\n  "
            + "\n  ".join(admitted),
        )


if __name__ == "__main__":
    unittest.main()
