from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from utils.cache.files import PROJECT_ROOT, iter_project_files_with_content
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_TASKS_MCP

if TYPE_CHECKING:
    from collections.abc import Iterator

HELPER = "roles/sys-svc-compose/tasks/utils/netns_request.yml"
FIXTURE_PATH = f"roles/x/{ROLE_FILE_TASKS_MAIN}"
ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "roles/web-app-xwiki/tasks/utils/http.yml",
        "🌐 XWIKI | send {{ xwiki_http_method }} {{ xwiki_http_url }}",
    ): "runs its own files/python/http_call.py with cookies, redirect policy, timeout and retry markers",
    (
        "roles/web-app-dashboard/tasks/_simpleicons_probe.yml",
        "🔍 Probe Simple Icons reachability per card slug",
    ): "the per-slug loop feeds its per-item results into the status map",
    (
        "roles/web-app-n8n/tasks/01_bootstrap.yml",
        "🔎 Probe n8n owner account via single login attempt",
    ): "retries until the answer content_type is JSON",
    (
        "roles/web-app-n8n/tasks/utils/ai_gateway.yml",
        "🤖 Provision the managed OpenAI credential against the gateway",
    ): "runs its own python script",
    (
        f"roles/web-app-n8n/{ROLE_FILE_TASKS_MCP}",
        "🔌 Provision the managed MCP trigger workflow",
    ): "runs its own python script",
    (
        f"roles/web-app-n8n/{ROLE_FILE_TASKS_MCP}",
        "🔌 Reconcile the managed agent over every discovered MCP provider",
    ): "runs its own python script",
    (
        "roles/web-app-peertube/tasks/design/apply.yml",
        "📤 PEERTUBE | Upload the corporate logos over fallback or own upload",
    ): "runs its own upload_logo.py",
    (
        "roles/web-app-peertube/tasks/rbac/provision.yml",
        "👤 PEERTUBE | Create the missing accounts of the role group members",
    ): "runs its own provision.py",
}

INLINE = (
    re.compile(r"\bhttp_request_program\b"),
    re.compile(r"\b[A-Z][A-Z0-9_]*_NETNS_PYTHON\b"),
    re.compile(r"\bhttp_request\.py\b"),
)
INDIRECT = re.compile(r"""\b(?:lookup|q|query)\s*\(\s*(?!['"\s])""")
INDIRECT_ALLOWLIST: dict[tuple[str, str], str] = {
    (
        f"roles/sys-front-inj-javascript/{ROLE_FILE_TASKS_MAIN}",
        "📄 Load JavaScript code for '{{ application_id }}'",
    ): "picks the template or the file lookup",
}
PARAM = re.compile(r"\bnetns_request_\w+")
MARKERS = ("http_request", "_NETNS_PYTHON", "netns_request")
INCLUDES = (
    "ansible.builtin.include_tasks",
    "include_tasks",
    "ansible.builtin.import_tasks",
    "import_tasks",
)
SECTIONS = ("block", "rescue", "always", "pre_tasks", "tasks", "post_tasks", "handlers")


def _strings(node) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, str):
        yield node


def _is_helper_include(task: dict) -> bool:
    return any("netns_request.yml" in str(task.get(key)) for key in INCLUDES)


def _tasks(node, guard: dict | None = None) -> Iterator[tuple[dict, dict | None]]:
    """Args:
        node: a parsed YAML document or task list.
        guard: the outermost enclosing block that carries a when.

    Returns:
        Every task dict with the outermost when-guarded block around it.
    """
    for task in node if isinstance(node, list) else []:
        if not isinstance(task, dict):
            continue
        yield task, guard
        inner = guard or (task if "block" in task and "when" in task else None)
        for section in SECTIONS:
            yield from _tasks(task.get(section), inner)


def _own(task: dict) -> dict:
    own = {key: value for key, value in task.items() if key not in SECTIONS}
    if _is_helper_include(task):
        own["vars"] = {
            key: value
            for key, value in (task.get("vars") or {}).items()
            if key != "netns_request_argv"
        }
    return own


def _indirect(path: str, doc) -> list[str]:
    if not isinstance(doc, list):
        hit = any(INDIRECT.search(text) for text in _strings(doc))
        return [f"{path}: names a lookup indirectly"] if hit else []
    return [
        f"{path}: task '{task.get('name')}' names a lookup indirectly"
        for task, _ in _tasks(doc)
        if (path, task.get("name")) not in INDIRECT_ALLOWLIST
        and any(INDIRECT.search(text) for text in _strings(_own(task)))
    ]


def _count(name: str, text: str) -> int:
    return len(re.findall(rf"\b{re.escape(name)}\b", text))


def _offenders(
    files: dict[str, str], allowlist: dict[tuple[str, str], str], others: dict[str, str]
) -> list[str]:
    """Args:
        files: YAML path to content, every file that names a marker.
        allowlist: (path, task name) pairs that may call the namespace inline.
        others: path to content of every further YAML file and template under
            roles/ and tasks/.

    Returns:
        One entry per inline call outside the allowlist, per template that
        names http_request_program, a NETNS_PYTHON fact or http_request.py, per
        task or file that names a lookup through a variable, per
        netns_request_* name outside the vars of a helper include, per helper
        include with its own when, and per when-guarded helper include whose
        result is produced twice or read outside that block.
    """
    found: list[str] = []
    docs: dict[str, object] = {}
    for path, text in others.items():
        if path.endswith(".j2") and any(rule.search(text) for rule in INLINE):
            found.append(f"{path}: template calls the namespace inline")
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        if path.endswith((".yml", ".yaml")) and INDIRECT.search(code):
            try:
                found += _indirect(path, load_yaml_str(text))
            except yaml.YAMLError:
                found.append(f"{path}: not parseable, so not checkable")
    for path, text in files.items():
        if path == HELPER:
            continue
        try:
            docs[path] = load_yaml_str(text)
        except yaml.YAMLError:
            found.append(f"{path}: not parseable, so not checkable")
    results: dict[str, list[tuple[str, dict | None]]] = {}
    for path, doc in docs.items():
        found += _indirect(path, doc)
        if not isinstance(doc, list):
            names = sorted(set(PARAM.findall(" ".join(_strings(doc)))))
            inline = any(rule.search(text) for text in _strings(doc) for rule in INLINE)
            found += [f"{path}: {name} outside a helper include" for name in names]
            found += [f"{path}: inline netns call"] if inline else []
            continue
        for task, guard in _tasks(doc):
            name = task.get("name")
            own = _own(task)
            texts = list(_strings(own))
            if (path, name) not in allowlist and any(
                rule.search(text) for text in texts for rule in INLINE
            ):
                found.append(f"{path}: task '{name}' calls the namespace inline")
            if _is_helper_include(task):
                if "when" in task:
                    found.append(
                        f"{path}: task '{name}' sets when: on a helper include"
                    )
                params = own.get("vars") or {}
                texts = [str(value) for value in _strings(list(params.values()))]
                texts += [str(v) for k, v in own.items() if k != "vars"]
                result = str(params.get("netns_request_result"))
                results.setdefault(result, []).append((path, guard))
            names = sorted(set(PARAM.findall(" ".join(texts))))
            found += [f"{path}: task '{name}' names {item}" for item in names]
    corpus = {path: json.dumps(doc) for path, doc in docs.items()} | others
    for result, producers in sorted(results.items()):
        guarded = [(path, guard) for path, guard in producers if guard is not None]
        for path, guard in guarded:
            if len(producers) > 1:
                found.append(
                    f"{path}: guarded result {result} has {len(producers)} producers"
                )
                continue
            outside = sum(
                _count(result, text) for other, text in corpus.items() if other != path
            )
            outside += _count(result, corpus[path]) - _count(result, json.dumps(guard))
            if outside:
                found.append(
                    f"{path}: guarded result {result} is read outside its when block"
                )
    return found


def _project() -> tuple[dict[str, str], dict[str, str]]:
    files: dict[str, str] = {}
    others: dict[str, str] = {}
    for name, text in iter_project_files_with_content(
        extensions=(".yml", ".yaml", ".j2"), exclude_tests=True
    ):
        rel = Path(name).relative_to(PROJECT_ROOT).as_posix()
        if rel.endswith((".yml", ".yaml")) and any(
            marker in text for marker in MARKERS
        ):
            files[rel] = text
        elif rel.startswith(("roles/", "tasks/")):
            others[rel] = text
    return files, others


def _fixture(text: str, others: dict[str, str] | None = None) -> list[str]:
    return _offenders({FIXTURE_PATH: text}, {}, others or {})


INCLUDE = (
    f"ansible.builtin.include_tasks: \"{{{{ lookup('path_absolute', '{HELPER}') }}}}\""
)
FIXTURES = {
    "classic": """
- name: probe
  ansible.builtin.command:
    argv: "{{ APP_NETNS_PYTHON }}"
    stdin: "{{ lookup('http_request_program', '') }}"
""",
    "netns_enter_with_script": """
- name: probe
  ansible.builtin.command:
    argv: "{{ APP_NETNS_ENTER + ['python3', '-'] }}"
    stdin: "{{ lookup('file', playbook_dir ~ '/roles/sys-svc-compose/files/python/http_request.py') }}"
""",
    "split_lookup": """
- name: probe
  ansible.builtin.shell:
    cmd: >-
      {{ lookup(
      'http_request_program', '') }}
""",
    "query": """
- name: probe
  ansible.builtin.set_fact:
    program: "{{ q('http_request_program', '') + query('http_request_program', '') }}"
""",
    "space_before_paren": """
- name: probe
  ansible.builtin.command:
    argv: "{{ APP_NETNS_ENTER + ['python3', '-'] }}"
    stdin: "{{ lookup ('http_request_program', '') }}"
""",
    "indirect_name": """
- name: probe
  vars:
    program: "{{ 'http_' ~ 'request' ~ '_program' }}"
  ansible.builtin.command:
    argv: "{{ APP_NETNS_ENTER + ['python3', '-'] }}"
    stdin: "{{ lookup(program, '') }}"
""",
    "outer_vars": f"""
- name: outer
  ansible.builtin.include_tasks: inner.yml
  vars:
    netns_request_body: LEAK
- name: helper
  {INCLUDE}
  vars:
    netns_request_argv: "{{{{ APP_NETNS_PYTHON }}}}"
    netns_request_result: app_answer
""",
    "guarded_reader_outside": f"""
- name: guarded
  when: app_ready | bool
  block:
    - name: helper
      {INCLUDE}
      vars:
        netns_request_result: app_answer
- name: reader
  ansible.builtin.debug:
    msg: "{{{{ app_answer.status }}}}"
""",
    "when_on_include": f"""
- name: helper
  {INCLUDE}
  when: app_ready | bool
  vars:
    netns_request_result: app_answer
""",
}
FIXTURE_FINDINGS = {
    "classic": [f"{FIXTURE_PATH}: task 'probe' calls the namespace inline"],
    "netns_enter_with_script": [
        f"{FIXTURE_PATH}: task 'probe' calls the namespace inline"
    ],
    "split_lookup": [f"{FIXTURE_PATH}: task 'probe' calls the namespace inline"],
    "query": [f"{FIXTURE_PATH}: task 'probe' calls the namespace inline"],
    "space_before_paren": [f"{FIXTURE_PATH}: task 'probe' calls the namespace inline"],
    "indirect_name": [f"{FIXTURE_PATH}: task 'probe' names a lookup indirectly"],
    "outer_vars": [f"{FIXTURE_PATH}: task 'outer' names netns_request_body"],
    "guarded_reader_outside": [
        f"{FIXTURE_PATH}: guarded result app_answer is read outside its when block"
    ],
    "when_on_include": [
        f"{FIXTURE_PATH}: task 'helper' sets when: on a helper include"
    ],
}
OTHER_FIXTURES = {
    "template": (
        {"roles/x/templates/request.py.j2": "{{ lookup('http_request_program', '') }}"},
        ["roles/x/templates/request.py.j2: template calls the namespace inline"],
    ),
    "indirect_without_marker": (
        {
            "roles/x/tasks/other.yml": (
                '- name: other\n  ansible.builtin.debug:\n    msg: "{{ lookup(name) }}"\n'
            )
        },
        ["roles/x/tasks/other.yml: task 'other' names a lookup indirectly"],
    ),
}
GUARDED_READER_INSIDE = f"""
- name: guarded
  when: app_ready | bool
  block:
    - name: helper
      {INCLUDE}
      vars:
        netns_request_result: app_answer
    - name: reader
      ansible.builtin.debug:
        msg: "{{{{ app_answer.status }}}}"
"""


class TestNetnsRequestSingleOwner(unittest.TestCase):
    def test_every_netns_http_call_goes_through_the_helper(self) -> None:
        files, others = _project()
        self.assertEqual(
            [],
            _offenders(files, ALLOWLIST, others),
            f"call the container namespace through {HELPER}: pass every "
            "netns_request_* name in the vars of its include only, put the "
            "condition into netns_request_skip, and read a result of a helper "
            "include inside a when block only within that block; a call the "
            "helper cannot express goes into ALLOWLIST as (path, task name)",
        )

    def test_every_allowlisted_task_still_calls_inline(self) -> None:
        files, others = _project()
        flagged = _offenders(files, {}, others)
        for path, name in ALLOWLIST:
            with self.subTest(path=path, name=name):
                self.assertIn(
                    f"{path}: task '{name}' calls the namespace inline", flagged
                )

    def test_negative_controls_flag_every_shape(self) -> None:
        for shape, text in FIXTURES.items():
            with self.subTest(shape=shape):
                self.assertEqual(FIXTURE_FINDINGS[shape], _fixture(text))
        for shape, (others, findings) in OTHER_FIXTURES.items():
            with self.subTest(shape=shape):
                self.assertEqual(findings, _fixture("[]", others))

    def test_a_reader_inside_the_when_block_passes(self) -> None:
        self.assertEqual([], _fixture(GUARDED_READER_INSIDE))


if __name__ == "__main__":
    unittest.main()
