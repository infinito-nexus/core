from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, meta, select_autoescape
from jinja2.exceptions import TemplateSyntaxError

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT
from .test_stack_batch_closure import P1_SEED, P2_SEED, STACK_ROLE, _sets, walk
from .test_stack_bridge import (
    ROLE_INCLUDES,
    TASK_INCLUDES,
    _tasks,
    bootstrap_roles,
    bridge_roles,
)
from .test_stack_guard import _role
from .test_stack_stage import STAGE, stage_files

if TYPE_CHECKING:
    from collections.abc import Iterator

PROVIDER_STEPS = (
    "roles/sys-svc-compose/tasks/utils/render_replicated_templates.yml",
    "roles/sys-svc-compose/tasks/utils/_render_one_template_apply.yml",
    "roles/sys-svc-compose/tasks/utils/network/create",
    "roles/svc-ai-litellm/tasks/utils/consumer_contract.yml",
    "roles/svc-ai-mcp-adapter/tasks/instance.yml",
    "roles/svc-ai-robot/tasks/utils/admit.yml",
    "roles/sys-svc-webserver-core/tasks/utils/mcp_edge_limits.yml",
    "roles/sys-sysctl/",
)
FRONT_STEPS = ("roles/sys-svc-webserver-core/tasks/utils/mcp_edge_limits.yml",)
PATH_ABSOLUTE = re.compile(r"lookup\(\s*'path_absolute'\s*,\s*'([^']+)'\s*\)")
TEMPLATE_INCLUDE = re.compile(r"\{%-?\s*(?:include|import|from)\s+['\"]([^'\"]+)['\"]")
FRONT_TEMPLATES = ("proxy.conf.j2",)
BACK_TEMPLATES = ("compose.yml.j2", "env.j2", "Dockerfile*")
VHOST_TEMPLATE_KEYS = ("extra_template", "location_extra_template")
MAGIC = frozenset(
    (
        "lookup",
        "query",
        "q",
        "now",
        "range",
        "dict",
        "lipsum",
        "cycler",
        "joiner",
        "namespace",
        "omit",
        "undef",
        "true",
        "false",
        "none",
        "True",
        "False",
        "None",
        "loop",
        "item",
        "inventory_hostname",
        "groups",
        "group_names",
        "hostvars",
        "playbook_dir",
        "role_path",
        "ansible_facts",
        "vars",
        "application_id",
        "domain",
    )
)


class _AnyCallable(dict):
    def __contains__(self, key: object) -> bool:
        return True

    def __getitem__(self, key: str) -> Any:
        return lambda *_args, **_kwargs: None

    def get(self, key: str, default: Any = None) -> Any:
        return self[key]


ENV = Environment(
    autoescape=select_autoescape(default_for_string=False),
    extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
)
ENV.filters = _AnyCallable(ENV.filters)
ENV.tests = _AnyCallable(ENV.tests)


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif isinstance(node, str):
        yield node


def names_in(text: str) -> set[str]:
    """Args:
        text: a template or a YAML value.

    Returns:
        the names it reads; ``<unparsable>`` when Jinja cannot parse it.
    """
    if "{{" not in text and "{%" not in text:
        return set()
    try:
        return set(meta.find_undeclared_variables(ENV.parse(text)))
    except TemplateSyntaxError:
        return {"<unparsable>"}


def _templates(role: str, seeds: list[Path]) -> list[Path]:
    templates = PROJECT_ROOT / "roles" / role / "templates"
    seen: list[Path] = []
    queue = [path for path in seeds if path.is_file()]
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.append(path)
        queue += [
            templates / ref
            for ref in TEMPLATE_INCLUDE.findall(read_text(str(path)))
            if (templates / ref).is_file()
        ]
    return seen


def _role_yaml(role: str, rel: str) -> Any:
    return load_yaml_any(
        str(PROJECT_ROOT / "roles" / role / rel), default_if_missing={}
    )


def _definitions(role: str) -> dict:
    return {
        **(_role_yaml(role, "defaults/main.yml") or {}),
        **(_role_yaml(role, "vars/main.yml") or {}),
    }


def _reads(role: str, templates: list[Path], values: list[str]) -> set[str]:
    names = set().union(
        *(names_in(read_text(str(p))) for p in templates),
        *(names_in(v) for v in values),
    )
    definitions, queue = _definitions(role), list(names)
    while queue:
        name = queue.pop()
        for text in _strings(definitions.get(name)):
            fresh = names_in(text) - names
            names |= fresh
            queue += fresh
    return names - MAGIC


def front_reads(role: str) -> set[str]:
    """Args:
        role: a bridge role.

    Returns:
        the names its front inputs read, transitively through its vars and
        defaults: proxy.conf.j2, the vhost templates its meta/server.yml
        names, and the values of meta/server.yml.
    """
    server = _role_yaml(role, "meta/server.yml") or {}
    vhosts = (server.get("vhosts") or {}) if isinstance(server, dict) else {}
    templates = PROJECT_ROOT / "roles" / role / "templates"
    seeds = [templates / name for name in FRONT_TEMPLATES] + [
        templates / str(vhost[key])
        for vhost in vhosts.values()
        if isinstance(vhost, dict)
        for key in VHOST_TEMPLATE_KEYS
        if key in vhost
    ]
    return _reads(role, _templates(role, seeds), list(_strings(server)))


def back_reads(role: str) -> set[str]:
    """Args:
        role: a bridge role.

    Returns:
        the names its backend inputs read, transitively through its vars and
        defaults: compose.yml.j2, env.j2, its Dockerfiles and the values of
        every meta file but meta/server.yml.
    """
    templates = PROJECT_ROOT / "roles" / role / "templates"
    seeds = [
        path for pattern in BACK_TEMPLATES for path in sorted(templates.glob(pattern))
    ]
    values = [
        text
        for path in sorted((PROJECT_ROOT / "roles" / role / "meta").glob("*.yml"))
        if path.name != "server.yml"
        for text in _strings(load_yaml_any(str(path), default_if_missing={}))
    ]
    return _reads(role, _templates(role, seeds), values)


def body_sets(role: str) -> set[str]:
    """Args:
        role: any role.

    Returns:
        the names its own task files set or register, its stack bridge aside.
    """
    tasks = PROJECT_ROOT / "roles" / role / "tasks"
    return set().union(
        *(
            _sets(path)
            for path in sorted(tasks.rglob("*.yml"))
            if path.relative_to(tasks).as_posix() != "utils/stack.yml"
        )
    )


def _group_names() -> set[str]:
    names: set[str] = set()
    for path in sorted((PROJECT_ROOT / "group_vars").rglob("*.yml")):
        data = load_yaml_any(str(path), default_if_missing={})
        names.update(data.keys() if isinstance(data, dict) else ())
    return names


def front_gate(roles: list[str]) -> list[str]:
    """Args:
        roles: the bridge roles.

    Returns:
        ``role: name`` for every name a front input reads that a role body
        after the loader sets. Names the batch sets for the same item, names
        set before the loader and group vars are exempt.
    """
    if not roles:
        return []
    p1 = walk(P1_SEED)
    same_item = set().union(
        *(
            _sets(path)
            for path in walk(
                P2_SEED, frozenset({*p1.flags, STACK_ROLE.replace("-", "_")})
            ).files
        )
    )
    bootstrap = bootstrap_roles(PROJECT_ROOT)
    early = set().union(*(body_sets(role) for role in bootstrap))
    late = set().union(
        *(
            body_sets(path.name)
            for path in (PROJECT_ROOT / "roles").iterdir()
            if path.name not in bootstrap
        )
    )
    exempt = same_item | early | _group_names()
    found = []
    for role in roles:
        reads = front_reads(role)
        found += [f"{role}: {name}" for name in sorted((reads & late) - exempt)]
        found += [f"{role}: <unparsable>"] if "<unparsable>" in reads else []
    return found


def back_gate(roles: list[str]) -> list[str]:
    """Args:
        roles: the bridge roles.

    Returns:
        ``role: name`` for every name a backend input reads that the role's
        own body sets.
    """
    found = []
    for role in roles:
        reads = back_reads(role)
        found += [
            f"{role}: {name}"
            for name in sorted((reads & body_sets(role)) - _group_names())
        ]
        found += [f"{role}: <unparsable>"] if "<unparsable>" in reads else []
    return found


def _targets(task: dict) -> Iterator[str]:
    for key in TASK_INCLUDES:
        spec = task.get(key)
        ref = spec.get("file") if isinstance(spec, dict) else spec
        if isinstance(ref, str):
            match = PATH_ABSOLUTE.search(ref)
            yield match.group(1) if match else ref
    for key in ROLE_INCLUDES:
        spec = task.get(key)
        if isinstance(spec, dict):
            tasks_from = str(spec.get("tasks_from", "main.yml"))
            yield f"roles/{spec.get('name')}/tasks/{tasks_from}"


def provider_steps(root: Path, roles: list[str]) -> list[str]:
    """Args:
        root: the repository root.
        roles: the bridge roles.

    Returns:
        ``path: step`` for every provider-side step a bridge role's own tasks
        call, except a step outside FRONT_STEPS that its stack stage reaches.
    """
    found = []
    for role in roles:
        staged = stage_files(root, role)
        for path in sorted((root / "roles" / role / "tasks").rglob("*.yml")):
            for task in _tasks(load_yaml_any(str(path), default_if_missing=[])):
                found += [
                    f"{path.relative_to(root)}: {target}"
                    for target in _targets(task)
                    if target.startswith(PROVIDER_STEPS)
                    and (path not in staged or target.startswith(FRONT_STEPS))
                ]
    return found


class TestStackBatchAdmission(unittest.TestCase):
    def test_bridge_roles_call_no_provider_step(self) -> None:
        self.assertEqual(provider_steps(PROJECT_ROOT, bridge_roles(PROJECT_ROOT)), [])

    def test_only_a_stage_may_call_a_backend_provider_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {
                "back": "roles/sys-svc-compose/tasks/utils/network/create.yml",
                "front": FRONT_STEPS[0],
            }
            include = "- include_tasks: \"{{{{ lookup('path_absolute', '{}') }}}}\"\n"
            _role(
                root,
                "web-app-staged",
                {
                    str(STAGE): include.format(calls["back"])
                    + include.format(calls["front"]),
                    "tasks/00_core.yml": include.format(calls["back"]),
                },
            )
            self.assertEqual(
                provider_steps(root, ["web-app-staged"]),
                [
                    f"roles/web-app-staged/tasks/00_core.yml: {calls['back']}",
                    f"roles/web-app-staged/{STAGE}: {calls['front']}",
                ],
            )

    def test_bridge_role_fronts_read_no_fact_set_after_the_loader(self) -> None:
        self.assertEqual(front_gate(bridge_roles(PROJECT_ROOT)), [])

    def test_bridge_role_backends_read_no_fact_of_their_own_body(self) -> None:
        self.assertEqual(back_gate(bridge_roles(PROJECT_ROOT)), [])


if __name__ == "__main__":
    unittest.main()
