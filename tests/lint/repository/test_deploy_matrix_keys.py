"""Lint: every ``matrix.<key>`` the deploy workflow reads must be a key the
matrix builder emits.

The deploy job's steps are wired to the matrix entry by name. GitHub resolves
an unknown ``matrix.<key>`` to the empty string rather than failing, so a typo
or a key the builder stopped emitting reaches the runner as an empty
environment variable and the job deploys something other than the row it was
given -- silently, in every case. An empty ``INFINITO_DISTROS`` does not abort:
``scripts/tests/deploy/distros.sh`` sources the env layer before its own
``:?`` guard, and ``scripts/meta/env/load.sh`` replaces an empty caller value
with the generated one, so the row sweeps all five distros instead of the one
it was assigned. An empty ``matrix.disable`` leaves a provider in the closure.

The keys are read from :func:`utils.github.variant.axes.assign` itself, minus
the ones :data:`cli.meta.ci.matrix.DROPPED` withholds from the JSON, so this
compares the workflow against the builder rather than against a second list.
"""

from __future__ import annotations

import re
import unittest

from cli.meta.ci import matrix
from tests.utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.github.variant import axes

DEPLOY_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"

_REFERENCE = re.compile(r"matrix\.([A-Za-z_][A-Za-z0-9_]*)")


def referenced_keys() -> set[str]:
    """Every ``matrix.<key>`` the workflow reads, ignoring commented-out YAML.

    A commented block is not a reference; counting one would red this lint for
    a line GitHub never evaluates.
    """
    live = "\n".join(
        line
        for line in read_text(str(DEPLOY_WORKFLOW)).splitlines()
        if not line.lstrip().startswith("#")
    )
    return set(_REFERENCE.findall(live))


def emitted_keys() -> set[str]:
    """The keys one matrix entry carries into the workflow."""
    entry = axes.assign(
        [{"name": "web-app-lint-probe", "variant": 0, "modes": ("compose",)}],
        sweep=0,
        tor_mode="auto",
        distros=axes.DISTROS,
        filesystems=axes.FILESYSTEMS,
    )[0]
    return set(entry) - set(matrix.DROPPED)


class TestDeployMatrixKeys(unittest.TestCase):
    def test_every_referenced_key_is_emitted(self) -> None:
        unknown = sorted(referenced_keys() - emitted_keys())
        self.assertEqual(
            unknown,
            [],
            f"{DEPLOY_WORKFLOW.name} reads matrix key(s) the builder does not "
            f"emit: {', '.join(unknown)}. GitHub resolves an unknown key to the "
            f"empty string, so the job runs with that value silently missing. "
            f"Emit it from utils.github.variant.axes.assign or drop the "
            f"reference.",
        )

    def test_the_withheld_rank_keys_are_not_referenced(self) -> None:
        leaked = sorted(referenced_keys() & set(matrix.DROPPED))
        self.assertEqual(
            leaked,
            [],
            f"{DEPLOY_WORKFLOW.name} reads rank key(s) the matrix JSON "
            f"withholds: {', '.join(leaked)}. They describe where the row sorts, "
            f"not how it deploys, and arrive empty.",
        )


if __name__ == "__main__":
    unittest.main()
