"""Checks whose verdict comes from System One rather than from an assertion.

A test oracle is the mechanism that decides pass or fail. Everywhere else in
this repository that mechanism is deterministic: a value equals another, a
file exists, a regex matches. Here it is a model, which makes the verdict
probabilistic and its calibration part of the test rather than a constant.

Two rules follow from that and every check in this suite keeps them:

* Read the answer as an ordering, never as an absolute. The server does not
  centre its probabilities on 0.5, so a fixed threshold would encode one
  deployment's calibration. Carry controls whose correct answers are known
  and opposite, and judge a candidate against them.
* Declare the run inconclusive when the controls fail to separate. A model
  that is not reading its input must not be allowed to return green.

The suite is not part of ``make test``: ``scripts/tests/code/run.sh`` picks
its directory from ``INFINITO_TEST_TYPE``, and only ``make test-oracle`` sets
it. It needs the tools lane, which that target brings up first.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUITE = "oracle"
