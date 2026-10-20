from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"


class TestWorkflowRunnerPinned(unittest.TestCase):
    def test_no_job_runs_on_a_latest_label(self) -> None:
        offenders: list[str] = []
        for path in sorted(_WORKFLOWS_DIR.glob("*.y*ml")):
            document = load_yaml_any(str(path), default_if_missing={}) or {}
            for job_id, job in (document.get("jobs") or {}).items():
                if not isinstance(job, dict) or "runs-on" not in job:
                    continue
                if "-latest" in str(job["runs-on"]):
                    offenders.append(f"{path.name}: {job_id}: {job['runs-on']}")

        if offenders:
            self.fail(
                f"{len(offenders)} job(s) run on a moving '*-latest' runner label. "
                "GitHub moves that label to the next OS release on its own "
                "schedule (ubuntu-latest jumped to 26.04 mid-run); pin the "
                "release, e.g. 'ubuntu-24.04', and move it in a dedicated "
                "change.\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
