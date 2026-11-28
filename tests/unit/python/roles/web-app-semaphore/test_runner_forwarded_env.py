from __future__ import annotations

import json
import unittest

from jinja2 import DictLoader, Environment, select_autoescape

from plugins.filter.dotenv import dotenv_quote, dotenv_unquote
from utils.cache.files import PROJECT_ROOT, read_text

from .test_workspace_runner import EGRESS, proxy_env, render

EXPORT_ENV = "roles/web-app-semaphore/templates/env/export-runner.j2"
CONTAINER_ENV = "roles/sys-svc-container/templates/env.j2"
FORWARDED = "SEMAPHORE_FORWARDED_ENV_VARS"
PROXY_NAMES = ("EGRESS_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
REQUIRED = ("EGRESS_PROXY", "HTTPS_PROXY")


def render_export_env():
    """Returns:
    ``templates/env/export-runner.j2`` rendered the way the template module
    renders it, as ``{name: value}`` with every value unquoted.
    """
    environment = Environment(
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        loader=DictLoader(
            {EXPORT_ENV: read_text(str(PROJECT_ROOT / EXPORT_ENV)), CONTAINER_ENV: ""}
        ),
    )
    environment.filters["to_json"] = json.dumps
    environment.filters["dotenv_quote"] = dotenv_quote
    environment.filters["bool"] = bool
    text = environment.get_template(EXPORT_ENV).render(
        SEMAPHORE_WEB_ROOT="https://semaphore.example.org",
        SEMAPHORE_RUNNER_TMP="/tmp/semaphore",
        SEMAPHORE_RUNNER_TOKEN_FILE="/run/secrets/semaphore-runner-token",
        SEMAPHORE_RUNNER_PROXY_ENV=proxy_env(EGRESS),
        SEMAPHORE_DEPLOY_ENABLED=False,
    )
    pairs = [line.split("=", 1) for line in text.splitlines() if "=" in line]
    return {name: dotenv_unquote(value) for name, value in pairs}


def forwarding_findings(env):
    """Args:
    env: the environment of a runner, ``{name: value}``.

    Returns:
        Why a task or a git child of that runner would miss a proxy variable
        the runner sets, or would get one it does not set.
    """
    if FORWARDED not in env:
        return [f"the runner sets no {FORWARDED}"]
    forwarded = json.loads(env[FORWARDED])
    defined = sorted(name for name in PROXY_NAMES if name in env)
    findings = [f"the runner sets no {name}" for name in REQUIRED if name not in env]
    if sorted(forwarded) != defined:
        findings.append(
            f"{FORWARDED} names {sorted(forwarded)}, the runner sets {defined}"
        )
    return findings


class RunnerForwardedEnvTests(unittest.TestCase):
    def runners(self):
        return {
            "workspace runner": render()["services"]["runner"]["environment"],
            "export runner": render_export_env(),
        }

    def test_each_runner_forwards_exactly_its_proxy_variables(self):
        for name, env in self.runners().items():
            with self.subTest(name):
                self.assertEqual(forwarding_findings(env), [])
                self.assertEqual(
                    {key: env[key] for key in REQUIRED},
                    {"EGRESS_PROXY": EGRESS, "HTTPS_PROXY": f"http://{EGRESS}"},
                )

    def test_negative_control_a_dropped_name_is_found(self):
        for name, env in self.runners().items():
            with self.subTest(name):
                forwarded = [
                    entry
                    for entry in json.loads(env[FORWARDED])
                    if entry != "EGRESS_PROXY"
                ]
                planted = {**env, FORWARDED: json.dumps(forwarded)}
                defined = sorted(key for key in PROXY_NAMES if key in env)
                self.assertEqual(
                    forwarding_findings(planted),
                    [
                        f"{FORWARDED} names {sorted(forwarded)}, the runner sets {defined}"
                    ],
                )

    def test_negative_control_a_runner_without_the_list_is_found(self):
        for name, env in self.runners().items():
            with self.subTest(name):
                planted = {key: value for key, value in env.items() if key != FORWARDED}
                self.assertEqual(
                    forwarding_findings(planted), [f"the runner sets no {FORWARDED}"]
                )


if __name__ == "__main__":
    unittest.main()
