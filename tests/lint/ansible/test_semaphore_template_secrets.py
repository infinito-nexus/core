from __future__ import annotations

import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
REFERENCE = re.compile(r"(?<![.\w])([A-Za-z_]\w*)((?:\.[A-Za-z_]\w*)*)")
CREDENTIAL_READ = re.compile(r"secrets\.credentials")


def load_project():
    """Returns:
    The module ``files/python/project.py``.
    """
    spec = spec_from_file_location(
        "semaphore_project_secrets", str(ROLE / "files" / "python" / "project.py")
    )
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _spec_task(node, name):
    if isinstance(node, list):
        for item in node:
            found = _spec_task(item, name)
            if found is not None:
                return found
    elif isinstance(node, dict):
        if name in (node.get("vars") or {}):
            return node
        for key in ("block", "rescue", "always"):
            found = _spec_task(node.get(key), name)
            if found is not None:
                return found
    return None


def workspace_scope():
    """Returns:
    ``(spec, scope)``: the raw ``semaphore_workspace_spec`` of
    ``tasks/utils/workspace/operation.yml`` and every name its values can
    read, the role vars, the vars of the converge task of
    ``tasks/utils/project/sync.yml``, whose ``semaphore_project_workspaces``
    sets the environment of the scheduled export templates, and the vars of
    that task.
    """
    task = _spec_task(
        load_yaml_any(str(ROLE / "tasks" / "utils" / "workspace" / "operation.yml")),
        "semaphore_workspace_spec",
    )
    converge = _spec_task(
        load_yaml_any(str(ROLE / "tasks" / "utils" / "project" / "sync.yml")),
        "semaphore_project_workspaces",
    )
    scope = {
        **load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN)),
        **converge["vars"],
        **task["vars"],
    }
    return task["vars"]["semaphore_workspace_spec"], scope


def _resolve(name, attributes, scope):
    value = scope[name]
    for attribute in attributes:
        if not isinstance(value, dict) or attribute not in value:
            return value
        value = value[attribute]
    return value


def reads(raw, scope):
    """Args:
    raw: a value as the role declares it, before templating.
    scope: the names it may read, as ``workspace_scope`` returns them.

    Returns:
        The raw text of the value and of everything it reads, transitively.
    """
    texts, pending, seen = [], [raw], set()
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
            continue
        if isinstance(value, list):
            pending.extend(value)
            continue
        text = str(value)
        texts.append(text)
        for name, path in REFERENCE.findall(LITERAL.sub("", text)):
            key = name + path
            if name in scope and key not in seen:
                seen.add(key)
                pending.append(_resolve(name, path.split(".")[1:], scope))
    return texts


def environments(spec, scope):
    """Args:
    spec: the raw ``semaphore_workspace_spec``.
    scope: as ``workspace_scope`` returns it.

    Returns:
        ``{template kind: {variable name: raw value}}`` for the environment of
        every template ``workspace apply`` creates and, as ``export schedule``,
        of the scheduled export templates the deploy creates; an expression
        that builds the environment counts as one entry under its own text.
    """
    found = {"ws": dict(spec["environment"])}
    for kind in load_project().PLATFORM_KINDS:
        found[kind] = _expression_entries(spec[kind]["environment"], scope)
    found["export schedule"] = _expression_entries(
        scope["semaphore_project_workspaces"]["export"]["environment"], scope
    )
    return found


def _expression_entries(expression, scope):
    entries = {expression: expression}
    for name, path in REFERENCE.findall(LITERAL.sub("", expression)):
        value = _resolve(name, path.split(".")[1:], scope) if name in scope else None
        if isinstance(value, dict):
            entries.update(value)
    return entries


def surveys():
    """Returns:
    ``{template kind: survey variable names}`` of every template ``workspace
    apply`` creates and of the scheduled export templates.
    """
    project = load_project()
    found = {"ws": {n for e in project.WORKSPACE_TEMPLATES for n, _ in e["survey"]}}
    for kind, entries in project.PLATFORM_TEMPLATES.items():
        found[kind] = {name for entry in entries for name, _ in entry["survey"]}
    found["export schedule"] = {
        name
        for entry in project.EXPORT_SCHEDULED_TEMPLATES
        for name, _ in entry["survey"]
    }
    return found


def credentials():
    """Returns:
    ``{credential name: role}`` of every ``roles/*/meta/secrets.yml``, the
    custom roles a ``make roles-pull`` placed in ``roles/`` included.
    """
    found = {}
    for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SECRETS}")):
        declared = load_yaml_any(str(path)) or {}
        for name in declared.get("credentials") or {}:
            found.setdefault(str(name).lower(), path.parent.parent.name)
    return found


def credential_of(name, declared):
    """Args:
    name: an environment or survey variable name.
    declared: as ``credentials`` returns it.

    Returns:
        ``role:credential`` the name is, or ends in, None for none.
    """
    lowered = name.lower()
    for credential, role in sorted(declared.items()):
        if lowered == credential or lowered.endswith("_" + credential):
            return f"{role}:{credential}"
    return None


def findings(envs, survey_names, declared, scope):
    """Args:
    envs: as ``environments`` returns it.
    survey_names: as ``surveys`` returns it.
    declared: as ``credentials`` returns it.
    scope: as ``workspace_scope`` returns it.

    Returns:
        One line per environment value that reads ``secrets.credentials`` and
        per environment or survey name that is a declared credential.
    """
    found = []
    for kind, entries in sorted(envs.items()):
        for name, raw in sorted(entries.items()):
            if any(CREDENTIAL_READ.search(text) for text in reads(raw, scope)):
                found.append(f"{kind} environment: {name} reads secrets.credentials")
            credential = None if name == raw else credential_of(name, declared)
            if credential:
                found.append(
                    f"{kind} environment: {name} is the credential {credential}"
                )
    for kind, names in sorted(survey_names.items()):
        for name in sorted(names):
            credential = credential_of(name, declared)
            if credential:
                found.append(f"{kind} survey: {name} is the credential {credential}")
    return found


class TestSemaphoreTemplateSecrets(unittest.TestCase):
    def test_workspace_templates_carry_no_secret(self):
        spec, scope = workspace_scope()
        envs = environments(spec, scope)
        self.assertTrue(all(envs.values()), envs)
        self.assertEqual(findings(envs, surveys(), credentials(), scope), [])

    def test_the_check_catches_a_planted_credential(self):
        spec, scope = workspace_scope()
        declared = credentials()
        self.assertIn("api_key_secret", declared)
        envs = environments(spec, scope)
        planted_scope = {
            **scope,
            "SEMAPHORE_PLANTED": {
                "ERP_KEY": "{{ lookup('config', 'web-app-erpnext', "
                "'secrets.credentials.api_key_secret') }}"
            },
        }
        planted_envs = {
            **envs,
            "ws": {
                **envs["ws"],
                "WORKSPACE_PLANTED": "{{ SEMAPHORE_PLANTED.ERP_KEY }}",
            },
        }
        planted_surveys = {**surveys(), "export": {"API_KEY_SECRET"}}
        self.assertEqual(
            findings(planted_envs, planted_surveys, declared, planted_scope),
            [
                "ws environment: WORKSPACE_PLANTED reads secrets.credentials",
                "export survey: API_KEY_SECRET is the credential web-app-erpnext:api_key_secret",
            ],
        )

    def test_the_check_reads_the_environment_of_the_scheduled_export_templates(
        self,
    ):
        spec, scope = workspace_scope()
        self.assertEqual(
            scope["semaphore_project_workspaces"]["export"]["environment"],
            "{{ SEMAPHORE_EXPORT_VARIABLES }}",
        )
        self.assertIn("BAO_ADDR", environments(spec, scope)["export schedule"])
        workspaces = scope["semaphore_project_workspaces"]
        expression = "{{ SEMAPHORE_EXPORT_VARIABLES | combine(SEMAPHORE_PLANTED) }}"
        planted_scope = {
            **scope,
            "SEMAPHORE_PLANTED": {
                "EXPORT_S3_KEY": "{{ lookup('config', application_id, "
                "'secrets.credentials.export_s3_secret_key') }}"
            },
            "semaphore_project_workspaces": {
                **workspaces,
                "export": {**workspaces["export"], "environment": expression},
            },
        }
        self.assertEqual(
            findings(
                environments(spec, planted_scope),
                surveys(),
                credentials(),
                planted_scope,
            ),
            [
                "export schedule environment: EXPORT_S3_KEY reads secrets.credentials",
                f"export schedule environment: {expression} reads secrets.credentials",
            ],
        )

    def test_a_custom_role_pulled_into_roles_is_read(self):
        roles = {
            p.parent.parent.name
            for p in Path(PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SECRETS}")
        }
        self.assertIn("web-app-erpnext", roles)
        self.assertEqual(
            credential_of(
                "STORE_SECRET_KEY_BASE", {"secret_key_base": "web-app-cst-store"}
            ),
            "web-app-cst-store:secret_key_base",
        )


if __name__ == "__main__":
    unittest.main()
