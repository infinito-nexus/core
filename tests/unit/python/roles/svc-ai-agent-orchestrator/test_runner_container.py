from __future__ import annotations

import ast
import re
import unittest

from jinja2 import Environment, StrictUndefined, meta, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.infra import RUNNER_CONTAINER_KEY
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-ai-agent-orchestrator"
SERVER = ROLE / "files" / "python" / "server.py"
CONTROLLER_RUNNER = "infinito-runner-7"


def _container_env(env_template: str, role_vars: str, environ: dict) -> dict:
    """Args:
        env_template: text of the role's env template.
        role_vars: text of the role's vars file.
        environ: the controller environment the ``env`` lookup reads.

    Returns:
        The rendered ``{key: value}`` of the template lines that set the runner key.
    """

    def lookup(name, key):
        if name != "env":
            raise AssertionError(f"unexpected lookup {name!r}")
        return environ.get(key, "")

    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.globals["lookup"] = lookup
    variables = load_yaml_str(role_vars)
    rendered = {}
    for line in env_template.splitlines():
        if not line.startswith(f"{RUNNER_CONTAINER_KEY}="):
            continue
        context = {
            name: env.from_string(str(variables[name])).render()
            for name in meta.find_undeclared_variables(env.parse(line))
        }
        key, _, value = env.from_string(line).render(**context).partition("=")
        rendered[key] = value
    return rendered


def _wired(env_template: str, role_vars: str) -> bool:
    """Args:
        env_template: text of the role's env template.
        role_vars: text of the role's vars file.

    Returns:
        Whether the rendered env file hands the container the runner the
        controller environment names.
    """
    environ = {RUNNER_CONTAINER_KEY: CONTROLLER_RUNNER}
    return _container_env(env_template, role_vars, environ) == environ


def _env_reads(source: str) -> set[str]:
    """Args:
        source: Python source of the server.

    Returns:
        Every literal key the server reads through ``ENV.get``.
    """
    return {
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "ENV"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }


class TestRunnerContainerWired(unittest.TestCase):
    def setUp(self) -> None:
        self.template = read_text(str(ROLE / "templates" / "env.j2"))
        self.vars = read_text(str(ROLE / ROLE_FILE_VARS_MAIN))

    def test_the_container_gets_the_runner_key_from_the_controller(self) -> None:
        self.assertTrue(_wired(self.template, self.vars))

    def test_the_server_reads_the_same_key(self) -> None:
        self.assertIn(RUNNER_CONTAINER_KEY, _env_reads(read_text(str(SERVER))))

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
