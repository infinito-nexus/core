from __future__ import annotations

import copy
import json
import shutil
import subprocess
import unittest

from ansible.plugins.filter.core import regex_search

from utils.cache.yaml import load_yaml_any

from ._incus import ROLE, environment

_TASKS = ROLE / "tasks" / "workspace"
TASKS = load_yaml_any(str(_TASKS / "certificate.yml"), default_if_missing=[])
APPLY = load_yaml_any(str(_TASKS / "apply.yml"), default_if_missing=[])
DESTROY = load_yaml_any(str(_TASKS / "destroy.yml"), default_if_missing=[])
A = "0c6f7a52-3d1e-4b8a-9f00-2a7b1c9d4e5f"
PROJECT = f"ws-{A}"
OPENSSL = shutil.which("openssl")


def _issue(tasks: list) -> list:
    return tasks


def _named(tasks: list, prefix: str) -> dict:
    return next(task for task in tasks if task.get("name", "").startswith(prefix))


def _render(value: object, variables: dict) -> object:
    env = environment()
    env.filters["regex_search"] = regex_search
    if isinstance(value, list):
        return [_render(item, variables) for item in value]
    if isinstance(value, str) and "{{" in value:
        return env.from_string(value).render(**variables)
    return value


def certificate_findings(tasks: list, keypair: str) -> list[str]:
    """Args:
        tasks: the parsed ``tasks/workspace.yml``.
        keypair: the stdout of the key generation task.

    Returns:
        Every way the issue steps put the private key on the Incus host or
        trust it beyond ``ws-<id>``.
    """
    issue = _issue(tasks)
    findings = []
    generate = _named(issue, "🔑 Generate the client key pair")
    if generate.get("delegate_to") != "localhost":
        findings.append("the key pair is generated off the controller")
    if generate.get("no_log") != "{{ MASK_CREDENTIALS_IN_LOGS | bool }}":
        findings.append("the key pair output is logged")
    variables = {
        "WORKSPACE": A,
        "item": {"fingerprint": "ab12"},
        "svc_virt_incus_ws_project": PROJECT,
        "svc_virt_incus_ws_keypair": {"stdout": keypair},
    }
    for task in issue:
        if (
            task.get("delegate_to") == "localhost"
            or "ansible.builtin.include_tasks" in task
        ):
            continue
        command = task.get("ansible.builtin.command", {})
        sent = str(_render(command.get("argv", []), variables)) + str(
            _render(command.get("stdin", ""), variables)
        )
        if "PRIVATE KEY" in sent:
            findings.append(f"{task['name']} sends the private key to the Incus host")
    trust = _named(issue, "🤝 Trust the certificate")
    argv = _render(trust["ansible.builtin.command"]["argv"], variables)
    if argv[:5] != ["incus", "config", "trust", "add-certificate", "/dev/stdin"]:
        findings.append(f"the certificate is trusted through {argv[:5]}")
    if "--restricted" not in argv or argv[argv.index("--projects") + 1] != PROJECT:
        findings.append(f"the trust entry reaches more than {PROJECT}: {argv}")
    stdin = _render(trust["ansible.builtin.command"]["stdin"], variables)
    if not stdin.startswith("-----BEGIN CERTIFICATE-----") or not stdin.endswith(
        "-----END CERTIFICATE-----"
    ):
        findings.append("the trust entry does not receive the certificate")
    if any("join" in str(task) or "trust add " in str(task) for task in issue):
        findings.append("a join token is issued for the workspace")
    return findings


def _keypair() -> str:
    generate = _named(_issue(TASKS), "🔑 Generate the client key pair")
    argv = _render(
        generate["ansible.builtin.command"]["argv"],
        {"WORKSPACE": A, "INCUS_WORKSPACE_CERT_DAYS": 30},
    )
    return subprocess.run(argv, capture_output=True, text=True, check=True).stdout


def _decision(trust: list, stored: dict) -> bool:
    task = _named(APPLY, "🧾 Decide whether")
    expression = task["ansible.builtin.set_fact"]["svc_virt_incus_ws_issue"]
    return (
        _render(
            expression,
            {
                "svc_virt_incus_ws_trust": trust,
                "openbao_kv_current": stored,
                "svc_virt_incus_ws_project": PROJECT,
            },
        ).strip()
        == "True"
    )


@unittest.skipUnless(OPENSSL, "openssl is not installed")
class TestWorkspaceCertificate(unittest.TestCase):
    def test_the_private_key_reaches_openbao_only(self):
        keypair = _keypair()
        self.assertIn("PRIVATE KEY", keypair)
        self.assertEqual(certificate_findings(TASKS, keypair), [])
        store = _named(_issue(TASKS), "🔐 Keep the client key")
        self.assertEqual(store["vars"]["openbao_kv_mount"], "{{ INCUS_TENANT_MOUNT }}")
        self.assertEqual(
            store["vars"]["openbao_kv_path"], "ws-{{ WORKSPACE }}-provision/incus"
        )
        key = _render(
            store["vars"]["openbao_kv_data"]["key"],
            {"svc_virt_incus_ws_keypair": {"stdout": keypair}},
        )
        self.assertTrue(key.startswith("-----BEGIN PRIVATE KEY-----"))

    def test_negative_control_a_key_sent_to_the_host_is_caught(self):
        mutant = copy.deepcopy(TASKS)
        trust = _named(_issue(mutant), "🤝 Trust the certificate")
        trust["ansible.builtin.command"]["stdin"] = (
            "{{ svc_virt_incus_ws_keypair.stdout }}"
        )
        self.assertIn(
            "🤝 Trust the certificate of ws-{{ WORKSPACE }} for its project alone sends the private key to the Incus host",
            certificate_findings(mutant, _keypair()),
        )

    def test_negative_control_an_unrestricted_trust_entry_is_caught(self):
        mutant = copy.deepcopy(TASKS)
        trust = _named(_issue(mutant), "🤝 Trust the certificate")
        trust["ansible.builtin.command"]["argv"].remove("--restricted")
        self.assertNotEqual(certificate_findings(mutant, _keypair()), [])

    def test_a_second_apply_issues_nothing(self):
        entry = {
            "name": PROJECT,
            "restricted": True,
            "projects": [PROJECT],
            "fingerprint": "ab12",
        }
        stored = {"key": "k", "fingerprint": "ab12"}
        self.assertFalse(_decision([entry], stored))
        self.assertTrue(_decision([], {}))
        self.assertTrue(_decision([entry], {}))
        self.assertTrue(_decision([{**entry, "restricted": False}], stored))
        self.assertTrue(
            _decision([{**entry, "projects": [PROJECT, "default"]}], stored)
        )
        self.assertTrue(_decision([entry], {**stored, "fingerprint": "cd34"}))
        self.assertTrue(_decision([entry, {**entry, "fingerprint": "ef56"}], stored))
        issue = _named(APPLY, "🔑 Issue the restricted client certificate")
        self.assertEqual(issue["when"], "svc_virt_incus_ws_issue | bool")

    def test_destroy_refuses_while_the_project_holds_an_instance(self):
        destroy = DESTROY
        refuse = _named(destroy, "🛑 Refuse to destroy")
        env = environment()
        env.filters["from_json"] = json.loads
        env.tests["skipped"] = lambda result: result.get("skipped", False)
        evaluate = env.compile_expression(refuse["ansible.builtin.assert"]["that"][0])

        def scope(stdout: str, skipped: bool = False) -> dict:
            return {
                "svc_virt_incus_ws_instances": {"stdout": stdout, "skipped": skipped}
            }

        self.assertFalse(evaluate(**scope('[{"name": "vm1"}]')))
        self.assertTrue(evaluate(**scope("[]")))
        self.assertTrue(evaluate(**scope("", skipped=True)))
        names = [task["name"] for task in destroy]
        project = names.index("🗑️ Remove the project ws-{{ WORKSPACE }}")
        self.assertLess(names.index(refuse["name"]), project)
        self.assertLess(
            project, names.index("🗑️ Remove the bridge of ws-{{ WORKSPACE }}")
        )


if __name__ == "__main__":
    unittest.main()
