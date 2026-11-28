from __future__ import annotations

import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from utils.cache.files import read_text

from . import PROJECT_ROOT

PASS = PROJECT_ROOT / "roles/svc-bkp-volume-2-local/files/test/workspace/pass.sh"
PROJECT = PROJECT_ROOT / "roles/web-app-semaphore/files/python/project.py"
WORKSPACE = " ws-${IDS[0]}"
DRILL_TASK = re.compile(r'drill task "\S+" ("[^"]+"|\S+)')
FIRST_TASK = 'drill task "${STATE}/result-${IDS[0]}.json" '


def provider_templates() -> set[str]:
    """
    Returns:
        The name, without the workspace, of each per-provider template the
        workspace apply creates.
    """
    spec = spec_from_file_location("semaphore_project", str(PROJECT))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return {
        f"{action}-{provider}"
        for action in module.ORDER_ACTIONS
        for provider in module.PROVISION_PROVIDERS
    }


def unknown_templates(source: str) -> list[str]:
    """
    Args:
        source: the drill script.

    Returns:
        Each template a ``drill task`` call names that the apply result of the
        drilled workspace does not hold.
    """
    known = provider_templates()
    findings = []
    for match in DRILL_TASK.findall(source):
        name = match.strip('"')
        if not (name.endswith(WORKSPACE) and name.removesuffix(WORKSPACE) in known):
            findings.append(name)
    return findings


class TestTheWorkspaceDrill(unittest.TestCase):
    def test_every_drill_task_names_a_provider_template_of_the_workspace(self) -> None:
        source = read_text(str(PASS))
        self.assertGreaterEqual(len(DRILL_TASK.findall(source)), 4)
        self.assertEqual(unknown_templates(source), [])

    def test_control_the_retired_shared_template_name_is_found(self) -> None:
        source = read_text(str(PASS))
        planted = source.replace(
            f'{FIRST_TASK}"provision-incus ws-${{IDS[0]}}"', f"{FIRST_TASK}provision", 1
        )
        self.assertNotEqual(planted, source)
        self.assertEqual(unknown_templates(planted), ["provision"])


if __name__ == "__main__":
    unittest.main()
