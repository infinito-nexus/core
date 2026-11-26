from __future__ import annotations

import io
import json
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import PurePath

from cli.meta.stacks.__main__ import main
from utils import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.infra_tools import idle_units
from utils.stacks.declaration import (
    CLASSES,
    Stack,
    load,
    problems,
    resolve,
    unaddressed,
)
from utils.stacks.makefile import MAKEFILE, calls, closure, make_calls, makefile_calls
from utils.stacks.reach import reaching
from utils.stacks.sites import removals, start_sites, starts, volume_removals
from utils.stacks.sources import SourceGraph, source_graph
from utils.stacks.starts import start_problems, without_named_start

CLASS_TABLE = {
    "cache": "always-on",
    "tools": "on-demand",
    "test-runner": "long-lived",
    "deploy": "on-demand",
}
TEST_RUNNER = ["cache", "test-runner"]
RESOLVED = {
    "test": TEST_RUNNER,
    "lint": TEST_RUNNER,
    "quality-high": TEST_RUNNER,
    "test-unit": TEST_RUNNER,
    "compose-deploy": ["cache", "deploy"],
    "compose-exec": ["cache", "deploy"],
    "i18n-translate": ["cache", "tools"],
    "i18n-tune": ["cache", "tools"],
    "test-oracle": ["cache", "test-runner", "tools"],
    "cache-evict": ["cache"],
    "swarm-role-sync": ["cache"],
    "dotenv": [],
}
RESOLVED_NAMED = {
    "test": ["cache", "deploy"],
    "quality-high": ["cache", "deploy"],
    "test-oracle": ["cache", "deploy", "tools"],
    "compose-deploy": ["cache", "deploy"],
}
NAMED_GUARD = '\tif [[ -z "${INFINITO_STACK_NAME:-}" ]]; then\n'
WRAPPER = (
    'case "${RUNNER}" in\n'
    "docker)\n"
    f"{NAMED_GUARD}"
    '\t\tinfinito_test_runner_exec "${PWD}" -- true\n'
    "\t\texit\n"
    "\tfi\n"
    '\techo "starting via make compose-up"\n'
    '\t"${MAKE:-make}" compose-up\n'
    "\t;;\n"
    "esac\n"
)
START_SOURCES = {
    "scripts/up.sh": "infinito_compose up -d\n",
    "scripts/wrap.sh": WRAPPER,
    "scripts/lib.sh": "infinito_test_runner_exec() { :; }\n# infinito_test_runner_exec x\n",
}
START_MAKEFILE = (
    "compose-up:\n\t@bash scripts/up.sh\nhalt:\n\t@true\nrest:\n\t@true\n"
    "check:\n\t@bash scripts/wrap.sh\n"
)
START_STACKS = {
    "deploy": Stack("deploy", "on-demand", (), ("compose-up",), ("halt",)),
    "test-runner": Stack(
        "test-runner", "long-lived", (), ("check",), ("rest",), "deploy"
    ),
}
TARGET_VOLUME_SITE = "cli/administration/deploy/development/target.py"
CODE_WRAPPER = "scripts/tests/code/wrapper.sh"
VOLUME_SOURCES = {
    "cli/a.py": 'compose.run(["rm", "--stop", "--volumes", SERVICE])\n',
    "cli/b.py": 'subprocess.run(["docker", "volume", "rm", name])\n',
    "cli/c.py": 'same = words == ["docker", "volume", "rm"]\nrun(["rm", "x"])\n',
    "cli/g.py": "compose.run(('rm', '-v', SERVICE))\n",
    "scripts/d.sh": "infinito_compose rm --stop -v target\n",
    "scripts/e.sh": 'docker volume rm "${LAB}_nfs-export"\n',
    "scripts/f.sh": "# infinito_compose rm -v target\n",
}
UNIT_NAMES = PROJECT_ROOT / "group_vars" / "all" / "06_daemons.yml"
UNIT_NAME = re.compile(r"(?m)^(\w+):\s*\"\{\{\s*lookup\('unit_name',\s*'([\w-]+)'")
TIMER_ON = re.compile(r"(?m)^\s*system_service_timer_enabled:\s*true\b")
HOST_TIMER_REMOVERS = {
    "svc-bkp-volume-2-local",
    "sys-ctl-cln-docker",
    "sys-ctl-rpr-container-soft",
}
FIXTURE = (
    ".PHONY: all\n"
    "all: first\n"
    '\t@"$(MAKE)" second\n'
    "\t@bash scripts/make/parallel.sh third \\\n"
    "\t\tfourth\n"
    "first:\n"
    "\t@true\n"
    "second:\n"
    "third:\n"
    "fourth:\n"
    "VARIABLE := all\n"
    "unrelated:\n"
    "\t@echo all\n"
)
SHELL_HELPER = "scripts/meta/compose.sh"
PYTHON_HELPER = "cli/helper.py"
SOURCES = {
    SHELL_HELPER: "infinito_compose() { :; }\n",
    "scripts/a.sh": "source scripts/meta/compose.sh\n",
    "scripts/b/run.sh": 'bash "${SCRIPT_DIR}/../a.sh"\n',
    "scripts/calls.sh": '"${MAKE:-make}" up\n',
    "scripts/printed.sh": "cat <<EOF\nmake up\nEOF\n",
    "scripts/echo.sh": 'echo "run make up first"\n# bash scripts/a.sh\n',
    "cli/__init__.py": "",
    PYTHON_HELPER: "",
    "cli/tool/__init__.py": "",
    "cli/tool/__main__.py": "",
    "cli/tool/go.py": "from cli.helper import x\n",
    "cli/tool/other.py": (
        "import cli.helper\n\n\ndef add_parser(sub):\n    sub.add_parser('reset')\n"
    ),
    "cli/tool/idle.py": "",
    "cli/lazy.py": "def f():\n    from .helper import x\n",
    "cli/typed.py": (
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
        "    from cli.helper import x\n"
    ),
    "cli/argv.py": 'CMD = ["python", "-m", "cli.helper"]\n',
    "cli/doc.py": '"""Calls scripts/a.sh."""\n',
}
REACHING_MAKEFILE = (
    "direct:\n\t@bash scripts/a.sh\n"
    "relative:\n\t@bash scripts/b/run.sh\n"
    "up:\n\t@bash scripts/a.sh\n"
    "scripted:\n\t@bash scripts/calls.sh\n"
    "printed:\n\t@bash scripts/printed.sh\n"
    "echoed:\n\t@bash scripts/echo.sh\n"
    'sub:\n\t@"$${PYTHON}" -m cli.tool go\n'
    'named:\n\t@"$${PYTHON}" -m cli.tool reset\n'
    'idle:\n\t@"$${PYTHON}" -m cli.tool idle\n'
    'lazy:\n\t@"$${PYTHON}" -m cli.lazy\n'
    'typed:\n\t@"$${PYTHON}" -m cli.typed\n'
    'argv:\n\t@"$${PYTHON}" -m cli.argv\n'
    'doc:\n\t@"$${PYTHON}" -m cli.doc\n'
    "aggregate: direct\n\t@$(MAKE) up\n"
)
REACHING = {
    "argv",
    "direct",
    "lazy",
    "named",
    "relative",
    "scripted",
    "sub",
    "up",
}
IMPORT_SOURCES = {
    SHELL_HELPER: "infinito_compose() { :; }\n",
    "cli/__init__.py": "",
    "cli/pkg/__init__.py": "from .heavy import go\n",
    "cli/pkg/heavy.py": f"import subprocess\nsubprocess.run(['bash', '{SHELL_HELPER}'])\n",
    "cli/pkg/light.py": "",
    "cli/light_user.py": "from cli.pkg.light import y\n",
    "cli/heavy_user.py": "from cli.pkg import go\n",
    "cli/dotted_user.py": "import cli.pkg.light\n\ncli.pkg.go()\n",
    "cli/dotted_light.py": "import cli.pkg.light\n\ncli.pkg.light.y()\n",
}
IMPORT_MAKEFILE = (
    'light:\n\t@"$${PYTHON}" -m cli.light_user\n'
    'heavy:\n\t@"$${PYTHON}" -m cli.heavy_user\n'
    'dotted:\n\t@"$${PYTHON}" -m cli.dotted_user\n'
    'dotted-light:\n\t@"$${PYTHON}" -m cli.dotted_light\n'
)
LINT_WRAPPER = "scripts/lint/wrapper.sh"
LINT_GUARD_EXIT = (
    '\t\tinfinito_test_runner_exec "${REPO_ROOT}" "${exec_env_args[@]}" -- '
    'bash "${INFINITO_SRC_DIR}/${target_script}" "$@"\n'
    "\t\texit\n"
)
CONDITIONAL_EXIT = '\t\tif [[ -n "${ONCE:-}" ]]; then\n\t\t\texit\n\t\tfi\n'
FD_EXEC = "\t\texec {lockfd}>&-\n"
NON_EXITS = (
    ("conditional exit", CONDITIONAL_EXIT),
    ("fd exec", FD_EXEC),
    ("and-list exit", '\t\t[[ -n "${ONCE:-}" ]] &&\n\t\texit\n'),
    ("or-list exit", "\t\ttrue ||\n\t\texit\n"),
    ("piped exit", "\t\ttrue |\n\t\texit\n"),
    ("and-list exit after a comment", "\t\ttrue && # once\n\t\texit\n"),
    ("stderr-piped exit", "\t\ttrue |&\n\t\texit\n"),
    ("quoted exit", '\t\techo "a\n\t\texit 0"\n'),
    ("heredoc closing exit", "\t\tcat <<-exit\n\t\texit\n"),
)
DOWN = "cli/administration/deploy/development/down.py"
EXPLICIT_REMOVERS = {"compose-down", "system-purge", "worktree-down"}
VOLUME_RECREATORS = {
    "compose-deploy",
    "environment-bootstrap",
    "environment-teardown",
    "network-ipv6-disable",
    "network-ipv6-restore",
    "network-refresh",
    "onboard",
    "roundtrip",
}
RECREATORS = VOLUME_RECREATORS | {"compose-network-recreate"}
ROLE_SUFFIXES = (".py", ".sh", ".j2")
CUSTOM_ROLE = "web-app-cst-"
ROLE_REMOVAL = re.compile(
    r"(?m)^(?![ \t]*#)[^\n]*?"
    r'(?:compose_cmd\(\s*"down"|\b(?:system|container) prune\b|\bcompose\b[^#\n]*\bdown\b)'
)
ROLE_REMOVERS = {
    "svc-bkp-volume-2-local",
    "sys-ctl-cln-docker",
    "sys-ctl-rpr-container-soft",
    "sys-svc-compose",
}
HOST_SOCKET = re.compile(r"docker\.sock|/var/run/docker\b")
LOCAL_STACK = ("compose.yml", "compose/")


def _relative(path: str) -> str:
    return PurePath(path).relative_to(PROJECT_ROOT).as_posix()


def _local_stack_files() -> dict[str, str]:
    return {
        rel: read_text(path)
        for path in iter_project_files()
        if (rel := _relative(path)).startswith(LOCAL_STACK)
    }


def _role_removers() -> set[str]:
    return {
        rel.split("/")[1]
        for path in iter_project_files(extensions=ROLE_SUFFIXES)
        if (rel := _relative(path)).startswith("roles/")
        and not rel.split("/")[1].startswith(CUSTOM_ROLE)
        and ROLE_REMOVAL.search(read_text(path))
    }


def _role_tasks() -> dict[str, str]:
    tasks: dict[str, list[str]] = {}
    for path in iter_project_files(extensions=(".yml",)):
        parts = _relative(path).split("/")
        if parts[0] == "roles" and len(parts) > 3 and parts[2] == "tasks":
            tasks.setdefault(parts[1], []).append(read_text(path))
    return {role: "\n".join(texts) for role, texts in tasks.items()}


def _host_unattended_roles() -> set[str]:
    tasks = _role_tasks()
    timers = {role for role, text in tasks.items() if TIMER_ON.search(text)}
    units = dict(UNIT_NAME.findall(read_text(str(UNIT_NAMES))))
    triggered = {
        role
        for name, role in units.items()
        if any(re.search(rf"\b{name}\b", tasks.get(timer, "")) for timer in timers)
    }
    return timers | triggered


def _fixture_graph(sources: dict[str, str]) -> SourceGraph:
    return SourceGraph(sources, sources.__getitem__)


def _unit_makefile(units: dict[str, str]) -> str:
    return "".join(
        f"unit-{index}:\n\t{line.split('=', 1)[1]}\n"
        for index, line in enumerate(
            line
            for text in units.values()
            for line in text.splitlines()
            if line.startswith(("ExecStart=", "ExecStartPre=", "ExecStop="))
        )
    )


class TestDeclaration(unittest.TestCase):
    def setUp(self) -> None:
        self.stacks = load()
        self.graph = makefile_calls()

    def test_every_stack_carries_its_lifecycle_class(self) -> None:
        self.assertEqual(
            {name: stack.lifecycle for name, stack in self.stacks.items()},
            CLASS_TABLE,
        )
        self.assertTrue(all(s.lifecycle in CLASSES for s in self.stacks.values()))

    def test_the_declaration_names_only_makefile_targets_and_known_stacks(
        self,
    ) -> None:
        self.assertEqual(problems(self.stacks, set(self.graph)), [])

    def test_every_stack_names_the_targets_that_need_it(self) -> None:
        for stack in self.stacks.values():
            with self.subTest(stack=stack.name):
                self.assertTrue(stack.targets)

    def test_every_wrapped_test_and_lint_target_needs_the_test_runner(
        self,
    ) -> None:
        wrapped = {
            target
            for target in self.graph
            if target.startswith(("test-unit-", "lint-"))
            or target in ("test-external", "test-integration", "test-lint")
        } - set(unaddressed())
        self.assertLessEqual(wrapped, set(self.stacks["test-runner"].targets))


class TestProblems(unittest.TestCase):
    def test_an_unknown_class_need_and_target_are_named(self) -> None:
        broken = {
            "a": Stack("a", "sometimes", ("ghost", "a"), ("no-such-target",)),
        }
        found = problems(broken, {"real"})
        self.assertEqual(len(found), 4)
        self.assertIn("class 'sometimes'", found[0])
        self.assertIn("needs ghost", found[1])
        self.assertIn("needs itself", found[2])
        self.assertIn("no-such-target", found[3])

    def test_a_target_that_starts_and_stops_one_stack_is_named(self) -> None:
        both = {"a": Stack("a", "on-demand", (), ("real",), ("real", "gone"))}
        found = problems(both, {"real"})
        self.assertEqual(len(found), 2)
        self.assertIn("target gone is not in the Makefile", found[0])
        self.assertIn("real both starts and stops it", found[1])


class TestReaching(unittest.TestCase):
    def setUp(self) -> None:
        self.found = reaching(
            REACHING_MAKEFILE,
            _fixture_graph(SOURCES),
            frozenset({SHELL_HELPER, PYTHON_HELPER}),
        )

    def test_exactly_the_recipes_that_run_a_helper_reach_it(self) -> None:
        self.assertEqual(set(self.found), REACHING)

    def test_a_make_call_inside_a_script_is_followed(self) -> None:
        self.assertEqual(
            self.found["scripted"],
            ["scripts/calls.sh", "make up", "scripts/a.sh", SHELL_HELPER],
        )

    def test_a_relative_source_resolves_against_the_script(self) -> None:
        self.assertEqual(
            self.found["relative"], ["scripts/b/run.sh", "scripts/a.sh", SHELL_HELPER]
        )

    def test_a_subcommand_resolves_by_module_and_by_parser_name(self) -> None:
        self.assertIn("cli/tool/go.py", self.found["sub"])
        self.assertIn("cli/tool/other.py", self.found["named"])

    def test_printed_text_quotes_comments_docstrings_and_typing_reach_nothing(
        self,
    ) -> None:
        for target in ("printed", "echoed", "doc", "typed", "idle"):
            with self.subTest(target=target):
                self.assertNotIn(target, self.found)

    def test_make_calls_skip_quoted_text(self) -> None:
        self.assertEqual(make_calls('make -C "${path}" compose-down'), {"compose-down"})
        self.assertEqual(make_calls('echo "run make up"'), set())


class TestDeployStackLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = source_graph()
        cls.makefile = read_text(str(MAKEFILE))
        cls.targets = calls(cls.makefile)
        cls.sinks = removals(cls.graph)
        cls.removers = cls._closure(cls.sinks)
        cls.starters = cls._closure(starts(cls.graph))
        cls.deploy = load()["deploy"]

    @classmethod
    def _closure(cls, sinks: frozenset[str]) -> set[str]:
        return closure(reaching(cls.makefile, cls.graph, sinks), cls.targets)

    def test_the_removal_sites_are_found(self) -> None:
        self.assertEqual(
            self.sinks,
            {
                DOWN,
                "cli/administration/deploy/development/recreate.py",
                "scripts/system/purge/system.sh",
            },
        )

    def test_every_remover_through_any_make_chain_is_pinned(self) -> None:
        self.assertEqual(self.removers, EXPLICIT_REMOVERS | RECREATORS)

    def test_only_the_explicit_teardown_targets_leave_it_down(self) -> None:
        self.assertEqual(self.removers - self.starters, EXPLICIT_REMOVERS)
        self.assertLessEqual(EXPLICIT_REMOVERS, set(self.deploy.stops))

    def test_every_other_remover_also_starts_it(self) -> None:
        self.assertEqual(self.removers & self.starters, RECREATORS)

    def test_the_recreators_that_drop_its_volumes_are_pinned(self) -> None:
        self.assertEqual(
            self._closure(frozenset({DOWN})) & RECREATORS, VOLUME_RECREATORS
        )

    def test_the_infra_runner_idle_timer_reaches_no_removal(self) -> None:
        units = idle_units(PROJECT_ROOT, "/venv/bin/python", {"KEY": "value"})
        makefile = _unit_makefile(units)
        self.assertIn("cli.administration.infra", makefile)
        self.assertEqual(reaching(makefile, self.graph, self.sinks), {})

    def test_a_unit_that_runs_a_teardown_target_is_caught(self) -> None:
        unit = {"stray.service": "[Service]\nExecStart=make compose-down\n"}
        makefile = _unit_makefile(unit) + self.makefile
        self.assertIn("unit-0", reaching(makefile, self.graph, self.sinks))

    def test_no_local_stack_mounts_the_host_docker_socket(self) -> None:
        self.assertEqual(
            [
                rel
                for rel, text in _local_stack_files().items()
                if HOST_SOCKET.search(text)
            ],
            [],
        )
        self.assertTrue(
            HOST_SOCKET.search("- /var/run/docker.sock:/var/run/docker.sock\n")
        )

    def test_the_role_scripts_that_remove_projects_or_containers_are_pinned(
        self,
    ) -> None:
        self.assertEqual(_role_removers(), ROLE_REMOVERS)
        self.assertTrue(ROLE_REMOVAL.search('compose_cmd("down", path, name)'))
        self.assertIsNone(ROLE_REMOVAL.search("# tearing a compose stack down races\n"))

    def test_the_role_installed_host_timers_that_remove_stacks_are_pinned(  # nocheck: test.text-presence -- repository-wide scan of every role's tasks and scripts for stack-removing timers
        self,
    ) -> None:
        self.assertEqual(ROLE_REMOVERS & _host_unattended_roles(), HOST_TIMER_REMOVERS)

    def test_only_the_target_reset_drops_part_of_it_with_its_volumes(self) -> None:
        self.assertEqual(volume_removals(self.graph), {TARGET_VOLUME_SITE})

    def test_every_target_that_drops_the_target_volumes_recreates_it(self) -> None:
        dropping = self._closure(volume_removals(self.graph))
        self.assertEqual(dropping, self.starters)
        self.assertIn("compose-up", dropping)
        self.assertIn("compose-target-reset", dropping)


class TestStartProblems(unittest.TestCase):
    def _problems(
        self,
        makefile: str = START_MAKEFILE,
        stacks: dict[str, Stack] = START_STACKS,
        wrapper: str = WRAPPER,
    ) -> list[str]:
        sources = {**START_SOURCES, "scripts/wrap.sh": wrapper}
        return start_problems(makefile, _fixture_graph(sources), stacks, ())

    def test_the_start_sites_are_split_per_stack(self) -> None:
        self.assertEqual(
            start_sites(_fixture_graph(START_SOURCES)),
            {"deploy": {"scripts/up.sh"}, "test-runner": {"scripts/wrap.sh"}},
        )

    def test_a_clean_declaration_has_no_problem(self) -> None:
        self.assertEqual(self._problems(), [])

    def test_a_stop_that_starts_through_make_or_a_prerequisite_is_named(
        self,
    ) -> None:
        for variant in (
            "halt:\n\t@$(MAKE) compose-up\n",
            "halt: compose-up\n\t@true\n",
        ):
            with self.subTest(variant=variant):
                found = self._problems(
                    START_MAKEFILE.replace("halt:\n\t@true\n", variant)
                )
                self.assertEqual(
                    found, ["halt stops or addresses no stack, yet starts deploy"]
                )

    def test_a_stop_of_another_stack_that_starts_one_is_named(self) -> None:
        for variant, started in (
            ("rest:\n\t@$(MAKE) compose-up\n", "deploy"),
            ("rest: check\n\t@true\n", "test-runner"),
        ):
            with self.subTest(variant=variant):
                found = self._problems(
                    START_MAKEFILE.replace("rest:\n\t@true\n", variant)
                )
                self.assertIn(
                    f"rest stops or addresses no stack, yet starts {started}", found
                )

    def test_only_the_guarded_named_start_of_a_wrapper_is_exempt(self) -> None:
        early = '\t"${MAKE:-make}" compose-up\n' + NAMED_GUARD
        for name, wrapper in (
            ("before the case", '"${MAKE:-make}" compose-deploy\n' + WRAPPER),
            ("before the guard", WRAPPER.replace(NAMED_GUARD, early)),
            ("guard without exit", WRAPPER.replace("\t\texit\n", "")),
            *(
                (tail_name, WRAPPER.replace("\t\texit\n", tail))
                for tail_name, tail in NON_EXITS
            ),
            (
                "else branch",
                WRAPPER.replace("\t\texit\n", "\t\texit\n\telse\n\t\ttrue\n"),
            ),
            (
                "guard in a subshell",
                WRAPPER.replace(NAMED_GUARD, "\t(\n" + NAMED_GUARD).replace(
                    "\tfi\n", "\tfi\n\t)\n"
                ),
            ),
        ):
            with self.subTest(name=name):
                found = self._problems(
                    START_MAKEFILE + "compose-deploy:\n\t@bash scripts/up.sh\n",
                    wrapper=wrapper,
                )
                self.assertTrue(
                    any(line.startswith("check starts deploy") for line in found),
                    found,
                )

    def test_the_named_start_is_blanked_and_nothing_else(self) -> None:
        kept = without_named_start(WRAPPER)
        self.assertNotIn('"${MAKE:-make}" compose-up', kept)
        self.assertIn("starting via make compose-up", kept)
        self.assertEqual(kept.count("\n"), WRAPPER.count("\n"))

    def test_an_exit_with_a_status_still_guards(self) -> None:
        for status in ("0", "1", "$?"):
            with self.subTest(status=status):
                kept = without_named_start(
                    WRAPPER.replace("\t\texit\n", f"\t\texit {status}\n")
                )
                self.assertNotIn('"${MAKE:-make}" compose-up', kept)

    def test_a_named_stack_start_outside_an_override_is_named(self) -> None:
        stacks = {
            **START_STACKS,
            "test-runner": Stack("test-runner", "long-lived", (), ("check",)),
        }
        found = self._problems(stacks=stacks)
        self.assertEqual(len(found), 1)
        self.assertIn("check starts deploy outside its targets", found[0])

    def test_a_starter_under_another_stack_is_named(self) -> None:
        stacks = {
            "deploy": Stack("deploy", "on-demand", (), ("compose-up", "check")),
            "test-runner": Stack("test-runner", "long-lived", (), (), (), "deploy"),
        }
        found = self._problems(stacks=stacks)
        self.assertEqual(len(found), 1)
        self.assertIn("check starts test-runner outside its targets", found[0])


class TestImportEdges(unittest.TestCase):
    def setUp(self) -> None:
        self.found = reaching(
            IMPORT_MAKEFILE,
            _fixture_graph(IMPORT_SOURCES),
            frozenset({SHELL_HELPER}),
        )

    def test_a_submodule_import_skips_its_package_re_exports(self) -> None:
        self.assertNotIn("light", self.found)
        self.assertNotIn("dotted-light", self.found)

    def test_a_re_export_read_through_the_bound_package_is_followed(self) -> None:
        self.assertEqual(
            self.found["dotted"],
            [
                "cli/dotted_user.py",
                "cli/pkg/__init__.py",
                "cli/pkg/heavy.py",
                SHELL_HELPER,
            ],
        )

    def test_a_package_import_follows_its_re_exports(self) -> None:
        self.assertEqual(
            self.found["heavy"],
            [
                "cli/heavy_user.py",
                "cli/pkg/__init__.py",
                "cli/pkg/heavy.py",
                SHELL_HELPER,
            ],
        )


class TestStopsOnTheRealTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = source_graph()
        cls.makefile = read_text(str(MAKEFILE))
        cls.stacks = load()
        cls.free = unaddressed()

    def _problems(
        self,
        old: str,
        new: str,
        wrapper: str | None = None,
        site: str = CODE_WRAPPER,
    ) -> list[str]:
        self.assertIn(old, self.makefile)
        graph = self.graph
        if wrapper is not None:
            graph = graph.rewritten({site: wrapper})
        return start_problems(
            self.makefile.replace(old, new, 1), graph, self.stacks, self.free
        )

    def test_the_tree_is_clean(self) -> None:
        self.assertEqual(self._problems("\n", "\n"), [])

    def test_a_stop_of_any_stack_that_starts_one_is_named(self) -> None:
        for target, old, new in (
            ("infra-down", "\ninfra-down:", "\ninfra-down: compose-up"),
            (
                "test-runner-down",
                "\t@bash scripts/tests/runner/down.sh\n",
                "\t@bash scripts/tests/runner/down.sh\n\t@$(MAKE) compose-up\n",
            ),
            ("i18n-pause", "\ni18n-pause:", "\ni18n-pause: lint-python"),
        ):
            with self.subTest(target=target):
                found = self._problems(old, new)
                self.assertTrue(
                    any(line.startswith(f"{target} stops") for line in found), found
                )

    def test_an_unguarded_start_in_the_test_wrapper_is_named(self) -> None:
        text = self.graph.text(CODE_WRAPPER)
        anchor = 'case "${INFINITO_TEST_RUNNER}" in\n'
        self.assertIn(anchor, text)
        found = self._problems(
            "\n",
            "\n",
            text.replace(anchor, '"${MAKE:-make}" compose-deploy\n' + anchor, 1),
        )
        self.assertIn("test-unit-python", {line.split(" ", 1)[0] for line in found})

    def test_a_lint_wrapper_guard_that_may_not_exit_is_no_guard(self) -> None:
        text = self.graph.text(LINT_WRAPPER)
        self.assertIn(LINT_GUARD_EXIT, text)
        for name, tail in NON_EXITS:
            with self.subTest(name=name):
                guard = LINT_GUARD_EXIT.replace("\t\texit\n", tail)
                found = self._problems(
                    "\n", "\n", text.replace(LINT_GUARD_EXIT, guard, 1), LINT_WRAPPER
                )
                self.assertIn("autoformat", {line.split(" ", 1)[0] for line in found})

    def test_every_wrapper_start_is_blanked_by_its_guard(self) -> None:
        wrappers = start_sites(self.graph)["test-runner"]
        self.assertEqual(len(wrappers), 3)
        for rel in sorted(wrappers):
            with self.subTest(wrapper=rel):
                text = self.graph.text(rel)
                starts = [
                    line
                    for line in text.splitlines()
                    if "compose-up" in make_calls(line)
                ]
                kept = without_named_start(text)
                self.assertEqual(len(starts), 1)
                self.assertNotIn(starts[0], kept.splitlines())
                self.assertEqual(kept.count("\n"), text.count("\n"))

    def test_swarm_role_sync_starts_no_deploy_stack(self) -> None:
        sites = start_sites(self.graph)
        self.assertNotIn(
            "swarm-role-sync", reaching(self.makefile, self.graph, sites["deploy"])
        )


class TestVolumeRemovals(unittest.TestCase):
    def test_rm_with_volumes_and_volume_rm_calls_are_found(self) -> None:
        self.assertEqual(
            volume_removals(_fixture_graph(VOLUME_SOURCES)),
            {"cli/a.py", "cli/b.py", "cli/g.py", "scripts/d.sh"},
        )


class TestCalls(unittest.TestCase):
    def test_prerequisites_make_calls_and_parallel_fan_out_are_followed(
        self,
    ) -> None:
        graph = calls(FIXTURE)
        self.assertEqual(graph["all"], {"first", "second", "third", "fourth"})
        self.assertEqual(graph["unrelated"], set())
        self.assertNotIn("VARIABLE", graph)


class TestResolve(unittest.TestCase):
    def setUp(self) -> None:
        self.stacks = load()
        self.graph = makefile_calls()

    def test_the_pinned_targets_start_exactly_their_stacks(self) -> None:
        for target, expected in RESOLVED.items():
            with self.subTest(target=target):
                self.assertEqual(resolve(target, self.stacks, self.graph), expected)

    def test_a_named_stack_takes_the_place_of_the_test_runner(self) -> None:
        for target, expected in RESOLVED_NAMED.items():
            with self.subTest(target=target):
                self.assertEqual(
                    resolve(target, self.stacks, self.graph, named=True), expected
                )

    def test_a_needed_stack_comes_first(self) -> None:
        stacks = {
            "late": Stack("late", "on-demand", ("early",), ("go",)),
            "early": Stack("early", "always-on", (), ()),
        }
        self.assertEqual(resolve("go", stacks, {"go": set()}), ["early", "late"])

    def test_an_unknown_target_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            resolve("no-such-target", self.stacks, self.graph)


class TestCli(unittest.TestCase):
    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_the_dry_run_prints_the_stacks_with_their_class(self) -> None:
        code, out, _ = self._run("compose-deploy")
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            {
                "target": "compose-deploy",
                "stacks": [
                    {"name": "cache", "class": "always-on"},
                    {"name": "deploy", "class": "on-demand"},
                ],
            },
        )

    def test_an_unknown_target_exits_non_zero(self) -> None:
        code, out, err = self._run("no-such-target")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no-such-target", err)


if __name__ == "__main__":
    unittest.main()
