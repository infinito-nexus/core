"""Every input handed to a reusable workflow must be declared by it.

GitHub validates a ``workflow_call`` before it creates the run, so passing an
undeclared key does not fail a job - it fails the whole run with a
``startup_failure`` whose only trace is a banner on the run page. Nothing in a
job log points at it. This check pairs each ``uses: ./.github/workflows/*.yml``
with the callee's declared inputs, and also demands that inputs marked required
without a default are actually supplied.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
_LOCAL_PREFIX = "./.github/workflows/"


def _load(path):
    return load_yaml_any(str(path), default_if_missing={}) or {}


def _triggers(document):
    return document.get("on") or document.get(True) or {}


def _declared_inputs(document):
    call = _triggers(document).get("workflow_call") or {}
    return call.get("inputs") or {}


class TestReusableWorkflowInputs(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = {
            path.name: _load(path) for path in sorted(_WORKFLOWS_DIR.glob("*.yml"))
        }

    def _calls(self):
        for name, document in self.documents.items():
            for job_id, job in (document.get("jobs") or {}).items():
                uses = job.get("uses") if isinstance(job, dict) else None
                if not isinstance(uses, str) or not uses.startswith(_LOCAL_PREFIX):
                    continue
                yield name, job_id, uses[len(_LOCAL_PREFIX) :], job.get("with") or {}

    def test_every_passed_input_is_declared(self) -> None:
        offenders: list[str] = []
        for caller, job_id, callee, passed in self._calls():
            document = self.documents.get(callee)
            self.assertIsNotNone(document, f"{caller}:{job_id} calls missing {callee}")
            declared = _declared_inputs(document)
            offenders += [
                f"{caller}:{job_id} passes '{key}' to {callee}, which does not declare it"
                for key in passed
                if key not in declared
            ]
        if offenders:
            self.fail(
                f"{len(offenders)} undeclared workflow input(s); each one is a "
                "startup_failure for the whole run:\n" + "\n".join(sorted(offenders))
            )

    def test_every_required_input_is_supplied(self) -> None:
        offenders: list[str] = []
        for caller, job_id, callee, passed in self._calls():
            declared = _declared_inputs(self.documents.get(callee) or {})
            offenders += [
                f"{caller}:{job_id} omits required '{key}' of {callee}"
                for key, spec in declared.items()
                if isinstance(spec, dict)
                and spec.get("required")
                and "default" not in spec
                and key not in passed
            ]
        if offenders:
            self.fail(
                f"{len(offenders)} missing required workflow input(s):\n"
                + "\n".join(sorted(offenders))
            )

    def test_the_check_sees_the_local_calls(self) -> None:
        self.assertGreater(len(list(self._calls())), 5)


if __name__ == "__main__":
    unittest.main()
