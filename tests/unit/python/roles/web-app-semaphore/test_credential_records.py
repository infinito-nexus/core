from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from utils.cache import ROLES_DIR
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from .files.provision._fake_provision import CREDENTIALS, load

provider_env = load("provision.provider_env")
INCLUDES = (
    "ansible.builtin.include_tasks",
    "include_tasks",
    "ansible.builtin.include_role",
    "include_role",
)
WRITER_MARKS = ("utils/kv.yml", "bao kv put")
EXPRESSION = re.compile(r"\{\{ ?([A-Za-z_][\w.]*) ?\}\}")
DICT_KEY = re.compile(r"'(\w+)':")
BAO_PUT = re.compile(r"bao kv put -mount=(\{\{.*?\}\}|\S+) (\{\{.*?\}\}|\S+) -")
PLACEHOLDERS = (
    ("ws-{{ WORKSPACE }}", "{workspace}"),
    ("{{ WORKSPACE }}", "{workspace}"),
    ("{{ semaphore_workspace_alias }}", "{workspace}"),
    ("{{ seaweedfs_ws.identity }}", "{workspace}-provision"),
    ("{{ inventory_hostname }}", "{host}"),
)
WRITTEN_ELSEWHERE = {
    "dns.route53": "semaphore_route53_record, from the fields of credentials.json",
    "dns.cloudflare": "semaphore_dns_writes, from the path and field of credentials.json",
    "providers.hetzner.secrets": "no core task",
    "providers.hetzner.workspace_secrets": "the store",
    "providers.ionos.secrets": "no core task",
    "providers.ionos.workspace_secrets": "the store",
    "providers.scs.secrets": "no core task",
}


def entries(credentials):
    """Args:
        credentials: the decoded ``credentials.json``.

    Returns:
        ``(label, KV v2 path, fields)`` of every record the provision runner
        reads.
    """
    state = credentials["state"]
    yield "state", state["path"], provider_env.mapping_fields(state["backend"])
    for flavor, entry in credentials["dns"].items():
        yield f"dns.{flavor}", entry["path"], provider_env.mapping_fields(entry["env"])
    for name, spec in credentials["providers"].items():
        for kind in ("secrets", provider_env.WORKSPACE_SECRETS):
            for secret in spec.get(kind, []):
                mapping = secret.get("env", {}) | secret.get("files", {})
                fields = provider_env.mapping_fields(mapping)
                yield f"providers.{name}.{kind}", secret["path"], fields


def _tasks(nodes):
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict):
            yield node
            for key in ("block", "rescue", "always"):
                yield from _tasks(node.get(key))


def writer_roles(roles):
    """Args:
        roles: a ``roles`` directory.

    Returns:
        Every role directory whose tasks write an OpenBao KV record.
    """
    paths = sorted(roles.glob("*/tasks/**/*.yml"))
    marked = {
        path.relative_to(roles).parts[0]
        for path in paths
        if any(mark in read_text(str(path)) for mark in WRITER_MARKS)
    }
    return [roles / name for name in sorted(marked)]


def _role_tasks(role):
    prefix = f"{role / 'tasks'}{os.sep}"
    files = sorted(
        Path(path)
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(prefix)
    )
    return [
        task for path in files for task in _tasks(load_yaml_str(read_text(str(path))))
    ]


def _names(role, tasks):
    variables = role / ROLE_FILE_VARS_MAIN
    text = read_text(str(variables)) if variables.is_file() else ""
    names = dict(load_yaml_str(text) or {})
    for task in tasks:
        if isinstance(task.get("vars"), dict):
            for name, value in task["vars"].items():
                names.setdefault(name, value)
        if isinstance(task.get("ansible.builtin.set_fact"), dict):
            for name, value in task["ansible.builtin.set_fact"].items():
                if isinstance(value, str):
                    names.setdefault(name, value)
    return names


def _resolved(text, names):
    for _ in range(3):
        text = EXPRESSION.sub(
            lambda match: str(names.get(match.group(1), match.group(0))), str(text)
        )
    for placeholder, name in PLACEHOLDERS:
        text = text.replace(placeholder, name)
    return text


def _data_fields(data, facts):
    if isinstance(data, dict):
        return set(data)
    text = str(data)
    named = [str(facts.get(name, "")) for name in EXPRESSION.findall(text)]
    return set(DICT_KEY.findall(" ".join([text, *named])))


def _writes(task, facts):
    variables = task.get("vars") or {}
    included = [str(task.get(key, "")) for key in INCLUDES]
    kv = any("web-app-openbao" in text and "utils/kv.yml" in text for text in included)
    if kv and "present" in str(variables.get("openbao_kv_state", "")):
        data = _data_fields(variables.get("openbao_kv_data"), facts)
        yield variables["openbao_kv_mount"], variables["openbao_kv_path"], data
    stdin = str((task.get("args") or {}).get("stdin", ""))
    for mount, path in BAO_PUT.findall(str(task.get("ansible.builtin.shell", ""))):
        yield mount, path, set(DICT_KEY.findall(stdin))


def written(roles):
    """Args:
        roles: the role directories to read, as :func:`writer_roles` lists them.

    Returns:
        ``{KV v2 path: fields}`` the tasks of those roles write, with the
        placeholders of ``credentials.json`` in the path.
    """
    records = {}
    for role in roles:
        tasks = _role_tasks(role)
        names = _names(role, tasks)
        facts = {}
        for task in tasks:
            fact = task.get("ansible.builtin.set_fact")
            facts |= fact if isinstance(fact, dict) else {}
        for task in tasks:
            for mount, path, fields in _writes(task, facts):
                key = f"{_resolved(mount, names)}/data/{_resolved(path, names)}"
                records.setdefault(key, set()).update(fields)
    return records


def findings(credentials, records):
    """Args:
        credentials: the decoded ``credentials.json``.
        records: the result of :func:`written`.

    Returns:
        One message per record field the runner reads that no core task
        writes at its path, beside the records ``WRITTEN_ELSEWHERE`` names.
    """
    messages = []
    for label, path, fields in entries(credentials):
        missing = sorted(fields - records.get(path, set()))
        if missing and label not in WRITTEN_ELSEWHERE:
            messages.append(f"{label}: no writer puts {', '.join(missing)} at {path}")
    return messages


def stale(credentials, records):
    """Args:
        credentials: the decoded ``credentials.json``.
        records: the result of :func:`written`.

    Returns:
        The labels of ``WRITTEN_ELSEWHERE`` that name no record, or whose
        records the core tasks now write in full.
    """
    open_labels = {
        label
        for label, path, fields in entries(credentials)
        if not fields <= records.get(path, set())
    }
    return sorted(set(WRITTEN_ELSEWHERE) - open_labels)


class TestCredentialRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = written(writer_roles(Path(ROLES_DIR)))

    def test_every_field_the_runner_reads_is_written_at_its_path(self):
        self.assertEqual(findings(CREDENTIALS, self.records), [])

    def test_every_record_written_elsewhere_lacks_a_core_writer(self):
        self.assertEqual(stale(CREDENTIALS, self.records), [])


if __name__ == "__main__":
    unittest.main()
