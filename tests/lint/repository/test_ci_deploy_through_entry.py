from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
ENTRY = "scripts/tests/deploy/job/entry.sh"
DEPLOYS = (
    re.compile(r"\bmake\b[^#]*\scompose-deploy\b"),
    re.compile(r"scripts/tests/deploy/ci/(?:all|one|dedicated)\.sh\b"),
    re.compile(r"scripts/tests/deploy/distros\.sh\b"),
    re.compile(r"scripts/tests/deploy/local/deploy/\S+\.sh\b"),
    re.compile(r"/00_one\.sh\b"),
)
NO_DEPLOY = "no workflow step deploys"
_CONTINUATION = re.compile(r"\\\n")
_SEPARATOR = re.compile(r"\n|;|&&|\|\||\||(?<![<>&])&(?![>&])")
_ENTRY_CALL = re.compile(
    r"^\s*(?:(?:then|else|do|exec|time)\s+)?"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
    r"(?:bash\s+)?(?:\./)?" + re.escape(ENTRY) + r"\s+\S"
)


def bypasses(run: str) -> tuple[int, list[str]]:
    """Args:
        run: the shell script of one workflow step.

    Returns:
        The number of deploy commands in ``run``, and every one of them that is
        not an argument of the job entry.
    """
    commands = _SEPARATOR.split(_CONTINUATION.sub(" ", run))
    deploys = [
        command.strip()
        for command in commands
        if any(deploy.search(command) for deploy in DEPLOYS)
    ]
    return len(deploys), [
        command for command in deploys if not _ENTRY_CALL.match(command)
    ]


def bypassing_steps(workflows: dict[str, dict]) -> list[str]:
    """Args:
        workflows: every parsed workflow by its file name.

    Returns:
        One ``<file>:<job>/<step>: <command>`` finding per deploy command that
        bypasses the job entry, and ``NO_DEPLOY`` when no step deploys at all.
    """
    findings: list[str] = []
    seen = 0
    for name, workflow in sorted(workflows.items()):
        for job_id, job in (workflow.get("jobs") or {}).items():
            for index, step in enumerate(job.get("steps") or []):
                label = f"step {index} {step.get('name', '')}".rstrip()
                count, bypassing = bypasses(str(step.get("run") or ""))
                seen += count
                findings.extend(
                    f"{name}:{job_id}/{label}: {command}" for command in bypassing
                )
    if not seen:
        findings.append(NO_DEPLOY)
    return findings


def workflow_texts() -> dict[str, str]:
    """Returns:
    The text of every workflow under ``.github/workflows`` by its file name.
    """
    return {path.name: read_text(str(path)) for path in sorted(WORKFLOWS.glob("*.yml"))}


def _steps(*runs: str) -> dict[str, dict]:
    return {"w.yml": {"jobs": {"d": {"steps": [{"run": run} for run in runs]}}}}


class TestCiDeployThroughEntry(unittest.TestCase):
    def test_the_entry_exists(self) -> None:
        self.assertTrue((PROJECT_ROOT / ENTRY).is_file())

    def test_every_workflow_deploy_step_calls_the_job_entry(self) -> None:
        workflows = {
            name: load_yaml_str(text) for name, text in workflow_texts().items()
        }
        self.assertEqual(bypassing_steps(workflows), [])

    def test_every_workflow_that_calls_the_entry_is_red_without_it(self) -> None:
        texts = workflow_texts()
        callers = {name for name, text in texts.items() if ENTRY in text}
        self.assertTrue(callers)
        stripped = {
            name: load_yaml_str(text.replace(f"./{ENTRY} ", ""))
            for name, text in texts.items()
        }
        flagged = {finding.split(":", 1)[0] for finding in bypassing_steps(stripped)}
        self.assertEqual(flagged, callers)

    def test_a_deploy_beside_an_entry_call_is_reported(self) -> None:
        for run in (
            f"./{ENTRY} true\nmake compose-deploy apps=web-app-dashboard",
            f"./{ENTRY} true && make compose-deploy apps=web-app-dashboard",
            f"./{ENTRY} true & ./scripts/tests/deploy/ci/all.sh",
            f"make compose-deploy apps=web-app-dashboard ./{ENTRY}",
        ):
            with self.subTest(run=run):
                self.assertEqual(len(bypassing_steps(_steps(run))), 1)

    def test_every_deploy_command_is_recognised(self) -> None:
        for run in (
            "make compose-deploy bundles=agents",
            'make -C "${GITHUB_WORKSPACE}" compose-deploy apps=web-app-dashboard',
            "./scripts/tests/deploy/ci/all.sh",
            "bash scripts/tests/deploy/ci/dedicated.sh --apps web-app-dashboard",
            './scripts/tests/deploy/distros.sh "${SCRIPTS}/00_one.sh"',
            "bash scripts/tests/deploy/local/deploy/main.sh",
        ):
            with self.subTest(run=run):
                findings = bypassing_steps(_steps(run))
                self.assertEqual(len(findings), 1)
                self.assertNotIn(NO_DEPLOY, findings)

    def test_an_entry_call_passes_in_every_shape(self) -> None:
        for run in (
            (
                f"set -euo pipefail\n./{ENTRY} make compose-deploy mode=update "
                "apps='web-app-dashboard' 2>&1 | tee /tmp/ansible.log"
            ),
            f"bash {ENTRY} ./scripts/tests/deploy/ci/all.sh",
            f"./{ENTRY} \\\n  make compose-deploy bundles=agents",
            f"if true; then ./{ENTRY} make compose-deploy; fi",
        ):
            with self.subTest(run=run):
                self.assertEqual(bypassing_steps(_steps(run)), [])

    def test_a_helper_under_the_ci_folder_is_no_deploy(self) -> None:
        self.assertEqual(
            bypassing_steps(
                _steps("./scripts/tests/deploy/ci/assert_no_deprecation_warnings.sh")
            ),
            [NO_DEPLOY],
        )


if __name__ == "__main__":
    unittest.main()
