from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

URI_MODULES = frozenset(
    {"uri", "uri_retry", "ansible.builtin.uri", "ansible.legacy.uri"}
)
NESTED_TASK_LISTS = ("block", "rescue", "always")
LOOPBACK_INTERNAL_URL = re.compile(
    r"^https?://(?:127\.0\.0\.1|localhost):\{\{[^}]*\.ports\.internal\."
)


def loopback_names(variables: object) -> set[str]:
    """Return the variables that hold a container-loopback URL.

    Args:
        variables: a parsed ``vars/main.yml``.

    Returns:
        Every top-level key whose string value starts with a loopback URL on a
        ``ports.internal`` port.
    """
    if not isinstance(variables, dict):
        return set()
    return {
        name
        for name, value in variables.items()
        if isinstance(value, str) and LOOPBACK_INTERNAL_URL.match(value)
    }


def uri_urls(tasks: object) -> list[tuple[str, str]]:
    """Return ``(task name, url)`` of every uri task, nested blocks included.

    Args:
        tasks: a parsed task file.
    """
    found: list[tuple[str, str]] = []
    stack = [tasks]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        stack.extend(node.get(key) for key in NESTED_TASK_LISTS)
        for module in sorted(URI_MODULES & set(node)):
            arguments = node[module]
            url = arguments.get("url") if isinstance(arguments, dict) else None
            if isinstance(url, str):
                found.append((str(node.get("name", "")), url))
    return found


def offenders(names: set[str], tasks: object) -> list[str]:
    """Return the names of the uri tasks whose url is a container-loopback URL.

    Args:
        names: the role's variables that hold such a URL.
        tasks: a parsed task file of the same role.
    """
    return [
        name
        for name, url in uri_urls(tasks)
        if LOOPBACK_INTERNAL_URL.match(url)
        or any(re.search(rf"\b{re.escape(var)}\b", url) for var in names)
    ]


def scan() -> list[str]:
    """Return ``<task file>: <task name>`` of every offending uri task."""
    root = Path(str(PROJECT_ROOT))
    names: dict[str, set[str]] = {}
    findings: list[str] = []
    for path in sorted(
        iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True)
    ):
        parts = Path(path).relative_to(root).parts
        if len(parts) < 4 or parts[0] != "roles" or parts[2] != "tasks":
            continue
        role = parts[1]
        if role not in names:
            role_vars = root / "roles" / role / ROLE_FILE_VARS_MAIN
            names[role] = (
                loopback_names(load_yaml_any(str(role_vars)))
                if role_vars.is_file()
                else set()
            )
        rel = Path(*parts).as_posix()
        findings.extend(
            f"{rel}: {name}" for name in offenders(names[role], load_yaml_any(path))
        )
    return findings


class TestUriNeverTargetsContainerLoopback(unittest.TestCase):
    def test_a_uri_task_on_a_loopback_internal_var_is_flagged(self) -> None:
        names = loopback_names(
            {
                "APP_API": "http://127.0.0.1:{{ lookup('config', application_id, "
                "'services.app.ports.internal.http') }}",
                "APP_PUBLIC": "http://{{ DOCKER_BIND_HOST }}:{{ lookup('config', "
                "application_id, 'services.app.ports.local.http') }}",
            }
        )
        tasks = [
            {
                "name": "outer",
                "block": [
                    {"name": "sign in", "uri_retry": {"url": "{{ APP_API }}/login"}},
                    {"name": "published", "uri": {"url": "{{ APP_PUBLIC }}/x"}},
                ],
            }
        ]
        self.assertEqual({"APP_API"}, names)
        self.assertEqual(["sign in"], offenders(names, tasks))

    def test_no_uri_task_targets_a_container_loopback_url(self) -> None:
        self.assertEqual(
            [],
            scan(),
            "a uri task runs outside the backend's network namespace, where "
            "its ports.internal port is not listening; call it through "
            "roles/sys-svc-compose/tasks/utils/netns_request.yml or through "
            "container exec",
        )


if __name__ == "__main__":
    unittest.main()
