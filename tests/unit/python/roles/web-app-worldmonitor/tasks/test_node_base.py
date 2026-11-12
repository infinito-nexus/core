from __future__ import annotations

import base64
import importlib.util
import unittest
from pathlib import PurePosixPath

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.docker.image.discovery import iter_role_images
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

APP = "web-app-worldmonitor"
ROLE = PROJECT_ROOT / "roles" / APP
SERVICES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
VARS = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
TASKS = load_yaml_str(read_text(str(ROLE / "tasks" / "00_core.yml")))
CLONE = "/opt/compose/worldmonitor/repository"
UPSTREAM_FROM = "node:24-alpine@sha256:feb76650b7195319268c59cb2d419c732d6c499b13bf5296f16ab59eb1f0a4f3"
SLURP = "ansible.builtin.slurp"
ASSERT = "ansible.builtin.assert"


def _filter():
    path = ROLE / "filter_plugins" / "dockerfile_foreign_bases.py"
    spec = importlib.util.spec_from_file_location("dockerfile_foreign_bases", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.dockerfile_foreign_bases


def _config(_name: str, _application_id: str, path: str):
    node = {"services": SERVICES}
    for part in path.split("."):
        node = node[part]
    return node


def _environment() -> Environment:
    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
    )
    env.filters["b64decode"] = lambda value: base64.b64decode(value).decode()
    env.filters["dockerfile_foreign_bases"] = _filter()
    env.filters["path_join"] = lambda parts: str(PurePosixPath(*parts))
    env.globals["lookup"] = _config
    return env


def _render(template: str, **context) -> str:
    return _environment().from_string(template).render(application_id=APP, **context)


def _stack_index() -> int:
    return next(
        index
        for index, task in enumerate(TASKS)
        if task.get("include_role", {}).get("name") == "sys-stk-full"
    )


def check_passes(dockerfiles: list[str]) -> bool:
    """Evaluate the role's FROM check against a clone holding ``dockerfiles``.

    Args:
        dockerfiles: the contents the slurp task would read, in loop order.

    Returns:
        The value of the assert task's ``that`` expression.
    """
    check = TASKS[_stack_index() + 2]
    env = _environment()
    slurped = {
        "results": [
            {"content": base64.b64encode(text.encode()).decode()}
            for text in dockerfiles
        ]
    }
    expression = check["vars"]["worldmonitor_foreign_bases"].strip()
    foreign = env.compile_expression(expression.removeprefix("{{").removesuffix("}}"))
    bases = foreign(
        worldmonitor_dockerfiles=slurped,
        WORLDMONITOR_NODE_FROM=_render(VARS["WORLDMONITOR_NODE_FROM"]),
    )
    passes = env.compile_expression(check[ASSERT]["that"])
    return bool(passes(worldmonitor_foreign_bases=bases))


class TestNodeBase(unittest.TestCase):
    def test_the_image_discovery_lists_the_node_base_by_digest(self):
        refs = [
            ref
            for ref in iter_role_images(PROJECT_ROOT)
            if ref.role == APP and ref.service == "node"
        ]
        digest = SERVICES["node"]["version"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].version, digest)
        self.assertEqual(refs[0].source, f"docker.io/library/node@{digest}")

    def test_the_declared_base_is_the_from_line_upstream_writes(self):
        self.assertEqual(_render(VARS["WORLDMONITOR_NODE_FROM"]), UPSTREAM_FROM)

    def test_the_check_reads_every_dockerfile_a_build_uses(self):
        context = {
            "compose_repository_path": CLONE,
            "WORLDMONITOR_REST_CONTEXT": _render(
                VARS["WORLDMONITOR_REST_CONTEXT"], compose_repository_path=CLONE
            ),
            "WORLDMONITOR_APP_DOCKERFILE": VARS["WORLDMONITOR_APP_DOCKERFILE"],
            "WORLDMONITOR_RELAY_DOCKERFILE": VARS["WORLDMONITOR_RELAY_DOCKERFILE"],
            "WORLDMONITOR_REST_DOCKERFILE": VARS["WORLDMONITOR_REST_DOCKERFILE"],
        }
        rendered = [
            _render(item, **context) for item in VARS["WORLDMONITOR_DOCKERFILES"]
        ]
        slurp = TASKS[_stack_index() + 1]
        self.assertEqual(
            rendered,
            [
                f"{CLONE}/Dockerfile",
                f"{CLONE}/Dockerfile.relay",
                f"{CLONE}/docker/Dockerfile.redis-rest",
            ],
        )
        self.assertEqual(slurp[SLURP]["src"], "{{ item }}")
        self.assertEqual(slurp["loop"], "{{ WORLDMONITOR_DOCKERFILES }}")

    def test_the_check_runs_after_the_clone_and_before_the_build(self):
        stack = TASKS[_stack_index()]
        slurp, check = TASKS[_stack_index() + 1], TASKS[_stack_index() + 2]
        self.assertIn(SLURP, slurp)
        self.assertIn(ASSERT, check)
        self.assertNotIn("compose_handlers_flush", stack.get("vars", {}))
        self.assertNotIn("compose_handlers_flush", VARS)
        for task in (slurp, check):
            self.assertEqual(task["when"], "IS_STACK_HOST | bool")

    def test_the_check_passes_on_the_pinned_upstream_from_lines(self):
        self.assertTrue(
            check_passes([f"FROM {UPSTREAM_FROM} AS builder\nFROM {UPSTREAM_FROM}\n"])
        )

    def test_the_check_fails_on_a_clone_whose_from_leaves_the_declared_base(self):
        moved = UPSTREAM_FROM.replace("@sha256:feb7", "@sha256:0000")
        for dockerfiles in (
            [f"FROM {UPSTREAM_FROM}\n", f"FROM {moved}\n"],
            ["FROM node:26-alpine\n"],
            [f"FROM {UPSTREAM_FROM} AS builder\nFROM python:3.13\n"],
        ):
            with self.subTest(dockerfiles=dockerfiles):
                self.assertFalse(check_passes(dockerfiles))


if __name__ == "__main__":
    unittest.main()
