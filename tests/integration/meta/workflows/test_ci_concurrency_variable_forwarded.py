"""Every workflow that sizes deploy chunks forwards the runner-slot variable.

The validation job counts the priority batches and every chunk's discover job
cuts its rows from the same ``cli.meta.ci.slots`` arithmetic. A workflow that
sizes chunks without ``vars.INFINITO_CI_CONCURRENCY`` cuts a different plan
than its siblings, so rows are skipped or deployed twice.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
KEY = "INFINITO_CI_CONCURRENCY"
FORWARD = "${{ vars.INFINITO_CI_CONCURRENCY }}"
_SIZERS = (
    "cli.meta.ci.matrix",
    "cli.meta.ci.plan",
    "cli.meta.ci.slots",
    "scripts/github/resolve/output_apps.sh",
    "scripts/github/resolve/priority_batches.sh",
)


def _sizing_workflows() -> list[Path]:
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if any(marker in read_text(str(path)) for marker in _SIZERS)
    ]


def _forwarded(path: Path) -> str | None:
    workflow = load_yaml_any(str(path), default_if_missing={}) or {}
    env = workflow.get("env") if isinstance(workflow, dict) else None
    return env.get(KEY) if isinstance(env, dict) else None


class TestCiConcurrencyVariableForwarded(unittest.TestCase):
    def test_every_chunk_sizing_workflow_forwards_the_variable(self) -> None:
        offenders = [
            path.name for path in _sizing_workflows() if _forwarded(path) != FORWARD
        ]
        self.assertEqual(
            offenders,
            [],
            f"declare `{KEY}: {FORWARD}` in the workflow-level env of every "
            "workflow that sizes deploy chunks",
        )

    def test_the_guard_finds_the_chunk_sizing_workflows(self) -> None:  # nocheck: test.text-presence -- vacuity guard of the workflow-wide forwarding lint  # fmt: skip
        self.assertGreaterEqual(
            len(_sizing_workflows()),
            2,
            "the validation and deploy workflows both size chunks; finding "
            "fewer means the markers drifted and the guard passes vacuously",
        )


if __name__ == "__main__":
    unittest.main()
