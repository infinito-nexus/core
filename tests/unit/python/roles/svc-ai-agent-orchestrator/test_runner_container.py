from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.infra import RUNNER_CONTAINER_KEY
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-ai-agent-orchestrator"
SERVER = ROLE / "files" / "python" / "server.py"


def _wired(env_template: str, role_vars: str) -> bool:
    """Args:
        env_template: text of the role's env template.
        role_vars: text of the role's vars file.

    Returns:
        Whether the template hands the container the one runner key, read from
        the controller environment and nowhere else.
    """
    line = re.search(
        rf"^{RUNNER_CONTAINER_KEY}=\{{\{{ (\w+) \}}\}}$", env_template, re.MULTILINE
    )
    if not line:
        return False
    source = re.search(rf"^{line.group(1)}: (.+)$", role_vars, re.MULTILINE)
    return bool(source) and source.group(1) == (
        f"\"{{{{ lookup('env', '{RUNNER_CONTAINER_KEY}') }}}}\""
    )


class TestRunnerContainerWired(unittest.TestCase):
    def setUp(self) -> None:
        self.template = read_text(str(ROLE / "templates" / "env.j2"))
        self.vars = read_text(str(ROLE / ROLE_FILE_VARS_MAIN))

    def test_the_container_gets_the_runner_key_from_the_controller(self) -> None:
        self.assertTrue(_wired(self.template, self.vars))

    def test_the_server_reads_the_same_key(self) -> None:
        self.assertIn(f'ENV.get("{RUNNER_CONTAINER_KEY}")', read_text(str(SERVER)))

    def test_a_template_without_the_key_is_flagged(self) -> None:
        stripped = self.template.replace(RUNNER_CONTAINER_KEY, "OTHER_KEY")
        self.assertFalse(_wired(stripped, self.vars))

    def test_a_hardcoded_container_name_is_flagged(self) -> None:
        planted = re.sub(
            r"^AGENT_ORCHESTRATOR_LANE_CONTAINER: .+$",
            'AGENT_ORCHESTRATOR_LANE_CONTAINER: "infinito-infra-runner"',
            self.vars,
            flags=re.MULTILINE,
        )
        self.assertFalse(_wired(self.template, planted))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
