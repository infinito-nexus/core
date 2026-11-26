from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

STORE = "webserver_csp_hashes_extra_by_vhost"
INJECTION_PASS = f"roles/sys-front-inj-all/{ROLE_FILE_TASKS_MAIN}"
FRONT_PROXY_DOMAIN = "roles/svc-stack/tasks/proxy/domain.yml"
FRONT_PROXY_VHOST = "roles/svc-stack/tasks/proxy/vhost.yml"
DECLARATION = "group_vars/all/04_webserver.yml"
YAML = (".yml", ".yaml")
SCANNED = ("roles/", "tasks/", "group_vars/", "host_vars/", "playbook")
SET_FACT = frozenset({"set_fact", "ansible.builtin.set_fact"})
INCLUDE_ROLE = frozenset(
    {
        "include_role",
        "import_role",
        "ansible.builtin.include_role",
        "ansible.builtin.import_role",
    }
)
INCLUDE_TASKS = frozenset(
    {
        "include_tasks",
        "import_tasks",
        "ansible.builtin.include_tasks",
        "ansible.builtin.import_tasks",
    }
)
OPEN = STORE + " | combine({domain: {}})"
WRITE = re.compile(re.escape(STORE) + r" \| add_csp_hash\(domain, ")


def _relative(path):
    return Path(path).relative_to(PROJECT_ROOT).as_posix()


def _is_task_file(relative):
    parts = relative.split("/")
    if parts[0] == "roles":
        return len(parts) > 3 and parts[2] == "tasks"
    return parts[0] == "tasks" or (len(parts) == 1 and parts[0].startswith("playbook"))


def _project_yaml():
    return [
        (_relative(path), path)
        for path in iter_project_files(extensions=YAML, exclude_tests=True)
    ]


def _files_naming(needle):
    return sorted(
        relative
        for relative, path in _project_yaml()
        if relative.startswith(SCANNED) and needle in read_text(path)
    )


def _load(relative):
    return load_yaml_any(PROJECT_ROOT / relative)


def _mappings(node, parent=""):
    if isinstance(node, dict):
        yield parent, node
        for key, value in node.items():
            yield from _mappings(value, str(key))
    elif isinstance(node, list):
        for item in node:
            yield from _mappings(item, parent)


def _expression(value):
    text = " ".join(str(value).split())
    return text.removeprefix("{{").removesuffix("}}").strip()


def _fact(task, name):
    for key in SET_FACT:
        facts = task.get(key)
        if isinstance(facts, dict) and name in facts:
            return _expression(facts[name])
    return ""


def _included_role(task):
    for key in INCLUDE_ROLE:
        spec = task.get(key)
        if isinstance(spec, dict):
            return spec["name"]
    return ""


def _target(spec):
    target = str(spec.get("tasks_from", "main"))
    return target if target.endswith(YAML) else target + ".yml"


def _task_includes(node):
    return {
        spec
        for _, mapping in _mappings(node)
        for key, spec in mapping.items()
        if key in INCLUDE_TASKS and isinstance(spec, str)
    }


def _writing_files(role):
    files = {
        path.name: path
        for path in (PROJECT_ROOT / "roles" / role / "tasks").glob("*.yml")
    }
    writing = {
        name for name, path in files.items() if "add_csp_hash" in read_text(str(path))
    }
    while True:
        reaching = {
            name
            for name, path in files.items()
            if _task_includes(load_yaml_any(path)) & writing
        }
        if reaching <= writing:
            return writing
        writing |= reaching


def _foreign_includes(role):
    return [
        (relative, _target(spec))
        for relative in _files_naming(role)
        if _is_task_file(relative) and relative != INJECTION_PASS
        for _, mapping in _mappings(_load(relative))
        for key, spec in mapping.items()
        if key in INCLUDE_ROLE and isinstance(spec, dict) and spec.get("name") == role
    ]


class TestCspHashStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assignments = [
            (relative, parent, node[STORE])
            for relative in _files_naming(STORE)
            for parent, node in _mappings(_load(relative))
            if STORE in node
        ]

    def test_the_store_is_declared_once_and_empty(self):
        declarations = [
            (relative, value)
            for relative, parent, value in self.assignments
            if parent not in SET_FACT
        ]
        self.assertEqual(declarations, [(DECLARATION, {})])

    def test_no_task_replaces_the_whole_store(self):  # nocheck: test.text-presence -- repository-wide lint over every parsed task file that writes the store  # fmt: skip
        foreign = [
            (relative, _expression(value))
            for relative, parent, value in self.assignments
            if parent in SET_FACT
            and not WRITE.match(_expression(value))
            and not (relative == INJECTION_PASS and _expression(value) == OPEN)
        ]
        self.assertEqual(foreign, [])

    def test_the_injection_pass_opens_its_vhost_before_any_injector(self):
        tasks = _load(INJECTION_PASS)
        opened = [
            index for index, task in enumerate(tasks) if _fact(task, STORE) == OPEN
        ]
        injectors = [
            index
            for index, task in enumerate(tasks)
            if _included_role(task).startswith("sys-front-inj-")
        ]
        self.assertEqual(len(opened), 1)
        self.assertTrue(injectors)
        self.assertLess(opened[0], min(injectors))

    def test_every_served_sibling_gets_an_injection_pass(self):
        main = _load(FRONT_PROXY_DOMAIN)
        fan_out = [
            task
            for task in main
            if any(task.get(key) == "proxy/vhost.yml" for key in INCLUDE_TASKS)
        ]
        self.assertEqual(len(fan_out), 1)
        self.assertEqual(
            fan_out[0]["loop"],
            "{{ lookup('network_siblings', front_proxy_vhost.domain) }}",
        )
        self.assertEqual(fan_out[0]["vars"]["domain"], "{{ front_proxy_domain }}")
        passes = [
            task
            for task in _load(FRONT_PROXY_VHOST)
            if _included_role(task) == "sys-front-inj-all"
        ]
        self.assertEqual(len(passes), 1)
        self.assertNotIn("when", passes[0])
        self.assertEqual(passes[0]["vars"]["domain"], "{{ front_proxy_domain }}")

    def test_every_writer_runs_inside_the_injection_pass(self):
        writers = sorted(
            {
                relative
                for relative, parent, value in self.assignments
                if parent in SET_FACT and WRITE.match(_expression(value))
            }
        )
        self.assertTrue(writers)
        injectors = {_included_role(task) for task in _load(INJECTION_PASS)}
        for relative in writers:
            role = relative.split("/")[1]
            self.assertIn(role, injectors, relative)
            for includer, target in _foreign_includes(role):
                self.assertNotIn(
                    target,
                    _writing_files(role),
                    f"{includer} reaches roles/{role}/tasks/{target}",
                )


if __name__ == "__main__":
    unittest.main()
