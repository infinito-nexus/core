from __future__ import annotations

import re
import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
_GATE_JOB = "fork-trust-gate"
_UNSAFE_CALL_INPUT = "allow_unsafe_checkout"
_UNSAFE_STEP_INPUT = "allow-unsafe-pr-checkout"
_GATE_BYPASS = re.compile(r"\b(?:always|cancelled|failure)\(\s*\)")


def _listens_to_pull_request_target(document) -> bool:
    triggers = document.get("on") or document.get(True) or {}
    if isinstance(triggers, str):
        return triggers == "pull_request_target"
    return "pull_request_target" in triggers


def _enabled(value) -> bool:
    return value not in (None, False, "false")


def _checks_out_pull_request_code(job: dict) -> bool:
    if _enabled((job.get("with") or {}).get(_UNSAFE_CALL_INPUT)):
        return True
    return any(
        _enabled((step.get("with") or {}).get(_UNSAFE_STEP_INPUT))
        for step in job.get("steps") or []
        if isinstance(step, dict)
    )


def _needs(job: dict) -> list[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


def _offenders(name: str, document) -> list[str]:
    offenders: list[str] = []
    for job_id, job in (document.get("jobs") or {}).items():
        if not isinstance(job, dict) or not _checks_out_pull_request_code(job):
            continue
        if _GATE_JOB not in _needs(job):
            offenders.append(f"{name}: {job_id}: does not need it")
        elif _GATE_BYPASS.search(str(job.get("if", ""))):
            offenders.append(f"{name}: {job_id}: runs past a failed gate")
    return offenders


class TestWorkflowForkCheckoutGated(unittest.TestCase):
    def test_pull_request_checkouts_under_pull_request_target_need_the_gate(
        self,
    ) -> None:
        offenders: list[str] = []
        for path in sorted(_WORKFLOWS_DIR.glob("*.y*ml")):
            document = load_yaml_any(str(path), default_if_missing={}) or {}
            if _listens_to_pull_request_target(document):
                offenders.extend(_offenders(path.name, document))

        if offenders:
            self.fail(
                f"{len(offenders)} pull_request_target job(s) check out pull "
                f"request code without depending on a green '{_GATE_JOB}'. Such "
                "a job runs fork content next to a write-scoped token, so it "
                "must wait for the gate that refuses fork PRs lacking the "
                "maintainer '🛡️ Trusted' label, and its if: must not use "
                "always(), cancelled() or failure().\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
