from __future__ import annotations

import base64
import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

from plugins.filter.dockerfile_foreign_bases import dockerfile_foreign_bases
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

TASKS = load_yaml_str(
    read_text(str(PROJECT_ROOT / "roles/sys-svc-compose/tasks/03_repository.yml"))
)
GIT = "git"
SLURP = "ansible.builtin.slurp"
ASSERT = "ansible.builtin.assert"
CLONE = "/opt/compose/worldmonitor/repository/"
BASE = "node:24-alpine@sha256:feb76650b7195319268c59cb2d419c732d6c499b13bf5296f16ab59eb1f0a4f3"
MOVED = BASE.replace("@sha256:feb7", "@sha256:0000")
BASES = {"node": BASE}
DOCKERFILES = {
    "worldmonitor": "Dockerfile",
    "redis-rest": "docker/Dockerfile.redis-rest",
}


def _index(module: str) -> int:
    return next(index for index, task in enumerate(TASKS) if module in task)


def _environment() -> ImmutableSandboxedEnvironment:
    env = ImmutableSandboxedEnvironment(undefined=StrictUndefined)
    env.filters.update(CoreFilters().filters())
    env.filters["dockerfile_foreign_bases"] = dockerfile_foreign_bases
    return env


def _evaluate(value: str, **context):
    """Evaluate one ``{{ ... }}`` task value or bare condition to its native type.

    Args:
        value: the string from the task file.
        context: the variables the expression reads.

    Returns:
        The value the expression yields.
    """
    expression = value.strip().removeprefix("{{").removesuffix("}}")
    return _environment().compile_expression(expression)(**context)


def foreign_bases(texts: list[str], bases: dict[str, str]) -> list[str]:
    """Evaluate the guard's offender list for Dockerfiles holding ``texts``.

    Args:
        texts: the Dockerfile contents the slurp task would read, in loop order.
        bases: the consumer's ``services.stack.checkout.build.bases``.

    Returns:
        The ``FROM`` references the guard refuses.
    """
    check = TASKS[_index(ASSERT)]
    reads = {
        "results": [
            {"content": base64.b64encode(text.encode()).decode()} for text in texts
        ]
    }
    return _evaluate(
        check["vars"]["compose_repository_foreign_bases"],
        compose_repository_dockerfile_reads=reads,
        compose_repository_bases=bases,
    )


def guard_passes(texts: list[str], bases: dict[str, str]) -> bool:
    check = TASKS[_index(ASSERT)]
    return bool(
        _evaluate(
            check[ASSERT]["that"],
            compose_repository_foreign_bases=foreign_bases(texts, bases),
        )
    )


class TestRepositoryBuildBases(unittest.TestCase):
    def test_the_guard_reads_and_checks_the_clone_after_the_pull(self):
        self.assertLess(_index(GIT), _index(SLURP))
        self.assertLess(_index(SLURP), _index(ASSERT))
        slurp, check = TASKS[_index(SLURP)], TASKS[_index(ASSERT)]
        self.assertIn(
            slurp["register"], check["vars"]["compose_repository_foreign_bases"]
        )
        self.assertNotIn("notify", slurp)

    def test_the_guard_reads_each_declared_dockerfile_inside_the_clone(self):
        slurp = TASKS[_index(SLURP)]
        items = _evaluate(slurp["loop"], compose_repository_dockerfiles=DOCKERFILES)
        self.assertEqual(
            [
                _evaluate(slurp[SLURP]["src"], item=item, compose_repository_path=CLONE)
                for item in items
            ],
            [f"{CLONE}Dockerfile", f"{CLONE}docker/Dockerfile.redis-rest"],
        )

    def test_only_a_consumer_declaring_dockerfiles_is_checked(self):
        when = TASKS[_index(ASSERT)]["when"]
        self.assertFalse(_evaluate(when, compose_repository_dockerfiles={}))
        self.assertTrue(_evaluate(when, compose_repository_dockerfiles=DOCKERFILES))
        self.assertEqual(
            _evaluate(TASKS[_index(SLURP)]["loop"], compose_repository_dockerfiles={}),
            [],
        )

    def test_the_guard_passes_on_the_declared_bases(self):
        texts = [f"FROM {BASE} AS builder\nFROM {BASE}\n", "FROM scratch\n"]
        self.assertTrue(guard_passes(texts, BASES))

    def test_the_guard_fails_on_a_from_outside_the_declared_bases(self):
        for texts in (
            [f"FROM {BASE}\n", f"FROM {MOVED}\n"],
            ["FROM node:26-alpine\n"],
            [f"FROM {BASE} AS builder\nFROM python:3.13\n"],
        ):
            with self.subTest(texts=texts):
                self.assertFalse(guard_passes(texts, BASES))

    def test_the_failure_names_the_offender_and_the_declared_bases(self):
        message = _environment().from_string(TASKS[_index(ASSERT)][ASSERT]["fail_msg"])
        rendered = message.render(
            compose_repository_foreign_bases=foreign_bases([f"FROM {MOVED}\n"], BASES),
            compose_repository_bases=BASES,
        )
        self.assertIn(MOVED, rendered)
        self.assertIn(BASE, rendered)


if __name__ == "__main__":
    unittest.main()
