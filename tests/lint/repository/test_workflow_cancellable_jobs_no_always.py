from __future__ import annotations

import re
import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
_LOCAL_PREFIX = "./.github/workflows/"
_ALWAYS = re.compile(r"\balways\(\s*\)")

_REPORTERS = frozenset(
    {
        ("call-orchestrator.yml", "done"),
        ("call-orchestrator.yml", "report-main-failures"),
    }
)


def _load(path):
    return load_yaml_any(str(path), default_if_missing={}) or {}


def _jobs(document):
    return {
        job_id: job
        for job_id, job in (document.get("jobs") or {}).items()
        if isinstance(job, dict)
    }


def _cancels_in_progress(document) -> bool:
    concurrency = document.get("concurrency")
    return (
        isinstance(concurrency, dict)
        and concurrency.get("cancel-in-progress", False) is not False
    )


def _cancellable(documents) -> set[str]:
    pending = [name for name, doc in documents.items() if _cancels_in_progress(doc)]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen or name not in documents:
            continue
        seen.add(name)
        pending += [
            job["uses"][len(_LOCAL_PREFIX) :]
            for job in _jobs(documents[name]).values()
            if str(job.get("uses", "")).startswith(_LOCAL_PREFIX)
        ]
    return seen


def _uses_always(job) -> bool:
    return bool(_ALWAYS.search(str(job.get("if", ""))))


class TestWorkflowCancellableJobsNoAlways(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = {
            path.name: _load(path) for path in sorted(_WORKFLOWS_DIR.glob("*.yml"))
        }
        self.cancellable = _cancellable(self.documents)

    def test_cancellable_jobs_do_not_use_always(self) -> None:
        offenders = [
            f"{name}:{job_id}: if: {' '.join(str(job['if']).split())}"
            for name in sorted(self.cancellable)
            for job_id, job in _jobs(self.documents[name]).items()
            if (name, job_id) not in _REPORTERS and _uses_always(job)
        ]
        if offenders:
            self.fail(
                f"{len(offenders)} job(s) in a cancellable workflow guard with "
                "always(). A cancel spares them, the run never ends, and the "
                "run that cancelled it waits on 'pending' behind it. Use "
                "!cancelled() instead:\n" + "\n".join(offenders)
            )

    def test_reporters_still_need_the_exemption(self) -> None:
        stale = [
            f"{name}:{job_id}"
            for name, job_id in sorted(_REPORTERS)
            if not _uses_always(_jobs(self.documents.get(name, {})).get(job_id, {}))
        ]
        self.assertEqual(
            stale, [], "exempted jobs no longer use always(); drop them from _REPORTERS"
        )

    def test_the_scope_reaches_the_deploy_chunks(self) -> None:
        self.assertLessEqual(
            {"call-orchestrator.yml", "call-test-deploy.yml", "call-validation.yml"},
            self.cancellable,
        )


if __name__ == "__main__":
    unittest.main()
