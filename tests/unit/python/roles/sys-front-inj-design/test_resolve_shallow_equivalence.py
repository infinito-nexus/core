from __future__ import annotations

import unittest
import unittest.mock
from typing import ClassVar

from ansible.plugins.loader import lookup_loader

from utils.cache.files import PROJECT_ROOT
from utils.tests.buckets import buckets, register

from .test_resolve_render_once import (
    DOMAIN,
    ONION,
    resolve_tasks,
    run_tasks,
)

SOURCES = (
    "templates/style.css.j2",
    "files/style.css",
    "files/logo.css",
    "templates/design.js.j2",
    "templates/design.js",
)
SHALLOW = "lookup('template_shallow', "
BUILTIN = "lookup('template', "


def _roles_with_design_sources() -> list[str]:
    return sorted(
        role.name
        for role in (PROJECT_ROOT / "roles").iterdir()
        if any((role / source).is_file() for source in SOURCES)
    )


def _builtin(value):
    if isinstance(value, str):
        return value.replace(SHALLOW, BUILTIN)
    if isinstance(value, dict):
        return {key: _builtin(item) for key, item in value.items()}
    return value


def base_tasks():
    """Return the resolve tasks with every shallow lookup swapped back.

    Returns:
        ``[style_task, script_task]`` rendering through ``ansible.builtin.template``.
    """
    return [_builtin(task) for task in resolve_tasks()]


def _outcome(tasks, app, vhost, logo) -> tuple[object, ...]:
    try:
        facts, renders = run_tasks(tasks, app, vhost, logo)
    except Exception as error:
        causes = []
        while error is not None:
            causes.append(f"{type(error).__name__}: {error}".replace(SHALLOW, BUILTIN))
            error = error.__cause__
        return ("error", causes)
    return ("facts", facts, {k: type(v) for k, v in facts.items()}, renders)


class TestResolveTasksRenderShallow(unittest.TestCase):
    def test_every_template_lookup_of_both_tasks_is_shallow(self) -> None:  # nocheck: test.text-presence -- non-vacuity guard: the render-equivalence tests swap this lookup in the parsed tasks  # fmt: skip
        for task in resolve_tasks():
            with self.subTest(task=task["name"]):
                text = repr(task)
                self.assertNotIn(BUILTIN, text)
                self.assertIn(SHALLOW, text)

    def test_the_base_overlay_restores_the_builtin_lookup(self) -> None:
        for task in base_tasks():
            with self.subTest(task=task["name"]):
                self.assertNotIn(SHALLOW, repr(task))
                self.assertIn(BUILTIN, repr(task))


class _ShallowMatchesBuiltinForEveryRole:
    """
    Args:
        roles: the roles with design sources the class renders.
    """

    roles: ClassVar[tuple[str, ...]]

    def test_every_role_variant_sets_identical_facts_or_fails_identically(
        self,
    ) -> None:
        shallow_tasks, builtin_tasks = resolve_tasks(), base_tasks()
        rendered = 0
        for app in self.roles:
            for vhost in (f"x.app.{DOMAIN}", f"x.app.{ONION}"):
                for logo in (True, False):
                    with self.subTest(app=app, vhost=vhost, logo=logo):
                        shallow = _outcome(shallow_tasks, app, vhost, logo)
                        builtin = _outcome(builtin_tasks, app, vhost, logo)
                        self.assertEqual(shallow, builtin)
                        rendered += shallow[0] == "facts"
        self.assertGreater(rendered, len(self.roles))


class TestShallowMatchesBuiltinForEveryRole(unittest.TestCase):
    def test_the_scan_finds_the_roles_with_design_sources(self) -> None:
        self.assertGreater(len(_roles_with_design_sources()), 70)

    def test_the_buckets_render_every_role_exactly_once(self) -> None:
        rendered = [role for bucket in ROLE_BUCKETS for role in bucket]
        self.assertEqual(sorted(rendered), _roles_with_design_sources())
        self.assertEqual(len(rendered), len(set(rendered)))

    def test_the_shallow_lookup_never_deep_copies_the_task_variables(self) -> None:
        real_get = lookup_loader.get
        copies = []

        def get(name, *args, **kwargs):
            plugin = real_get(name, *args, **kwargs)
            if name == "template":
                original = plugin.run

                def watched(terms, variables=None, **options):
                    copies.append(type(variables).__name__)
                    return original(terms, variables=variables, **options)

                plugin.run = watched
            return plugin

        with unittest.mock.patch.object(lookup_loader, "get", side_effect=get):
            run_tasks(resolve_tasks(), "web-svc-logout", f"x.app.{DOMAIN}", True)
        self.assertTrue(copies)
        self.assertEqual(set(copies), {"_SharedVariables"})


ROLE_BUCKETS = buckets(_roles_with_design_sources(), 6)
for _index, _bucket in enumerate(ROLE_BUCKETS):
    register(
        globals(),
        f"TestShallowMatchesBuiltinForEveryRole_bucket_{_index}",
        _ShallowMatchesBuiltinForEveryRole,
        roles=_bucket,
    )


if __name__ == "__main__":
    unittest.main()
