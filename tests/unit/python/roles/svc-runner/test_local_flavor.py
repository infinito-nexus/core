from __future__ import annotations

import configparser
import importlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_META_USERS
from utils.runner import loop, role, store

render = importlib.import_module("tests.unit.python.roles.svc-runner._render")

CORE_TASKS = "00_core.yml"
QUEUE_TASKS = "01_queue.yml"
INSTANCE_TASKS = "03_instance.yml"
TEMPLATE_MODULE = "ansible.builtin.template"
HEALTHCHECK_DISABLED = ["NONE"]

REGISTRATION_KEYS = (
    "RUNNER_NAME",
    "RUNNER_LABELS",
    "RUNNER_GITHUB_OWNER",
    "RUNNER_GITHUB_REPO",
    "RUNNER_API_TOKEN",
)
REGISTRATION_CALLS = ("config.sh", "registration-token", "run.sh")
CHECKOUT_KEYS = ("RUNNER_GIT_REF", "GITHUB_REPOSITORY", "GITHUB_REPOSITORY_OWNER")
INSTANCE_KEYS = (
    "COMPOSE_PROJECT_NAME",
    "INFINITO_RUNNER_PREFIX",
    "INFINITO_SUBNET",
    "INFINITO_DOCKER_VOLUME",
    "INVENTORY_DIR",
)
BINARY_MODULES = ("uri_retry", "get_url_retry", "unarchive", "set_fact")
BINARY_MARKERS = ("actions/runner", "actions-runner", "runner_resolved_version")
ASSERT_MODULES = ("assert", "ansible.builtin.assert")
QUEUE_ENV_KEYS = (
    "INFINITO_RUNNER_QUEUE_DIR",
    "INFINITO_RUNNER_CHECKOUT",
    "RUNNER_SRC_DIR",
)


STUB_PYTHON = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "${PWD}" "${PYTHONPATH:-}" "$@" >> "${STUB_LOG}"\n'
)


def _local_entrypoint(overrides: dict[str, str | None]) -> tuple[int, list[dict]]:
    """
    Args:
        overrides: environment values to set, or to drop when None.

    Returns:
        The entrypoint's exit code and one ``{src, cwd, pythonpath, argv}`` per
        python3 start, ``src`` being the RUNNER_SRC_DIR it was given.
    """
    flavors = render.role_vars()["RUNNER_FLAVORS"]
    script = render.ROLE / "files" / flavors["local"]["entrypoint"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir, src = root / "bin", root / "src"
        bin_dir.mkdir()
        src.mkdir()
        stub = bin_dir / "python3"
        stub.write_text(STUB_PYTHON, encoding="utf-8")
        stub.chmod(0o755)
        log = root / "python3.log"
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(log),
            "COMPOSE_PROJECT_NAME": "runner-1",
            "INFINITO_RUNNER_QUEUE_DIR": str(root / "queue"),
            "INFINITO_RUNNER_INSTALL_DIR": str(root / "install"),
            "INFINITO_RUNNER_CHECKOUT": str(root / "install" / "checkout"),
            "INFINITO_RUNNER_IMAGE": "toolchain:latest",
            "RUNNER_SRC_DIR": str(src),
        }
        for key, value in overrides.items():
            if value is None:
                env.pop(key)
            else:
                env[key] = value
        result = subprocess.run(
            ["bash", str(script)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        written = ""
        if log.exists():
            written = log.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        lines = written.splitlines()
    calls = (
        [{"src": str(src), "cwd": lines[0], "pythonpath": lines[1], "argv": lines[2:]}]
        if lines
        else []
    )
    return result.returncode, calls


def _services(text: str) -> dict:
    return load_yaml_str(text)["services"]


def _root_mounts(text: str, roots: list[str]) -> dict[str, list[str]]:
    wanted = {f"{root}:{root}:ro" for root in roots}
    return {
        name: [volume for volume in service["volumes"] if volume in wanted]
        for name, service in _services(text).items()
    }


def _clauses(task: dict) -> list[str]:
    when = task.get("when", [])
    return when if isinstance(when, list) else [when]


def _flatten(tasks: list[dict], inherited: tuple[str, ...] = ()):
    for task in tasks:
        clauses = (*inherited, *_clauses(task))
        if "block" in task:
            yield from _flatten(task["block"], clauses)
        else:
            yield task, clauses


def _tasks(name: str) -> list[dict]:
    return load_yaml_any(str(render.ROLE / "tasks" / name))


def _binary_tasks() -> list[tuple[str, str]]:
    tasks = [*_tasks(CORE_TASKS), *_tasks(INSTANCE_TASKS)]
    return [
        (task["name"], " and ".join(f"({clause})" for clause in clauses) or "true")
        for task, clauses in _flatten(tasks)
        if any(
            marker in str(task[module])
            for module in BINARY_MODULES
            if module in task
            for marker in BINARY_MARKERS
        )
    ]


def _assert_tasks() -> list[dict]:
    return [
        task
        for task in _tasks(CORE_TASKS)
        if any(module in task for module in ASSERT_MODULES)
    ]


def _assert_module(task: dict) -> dict:
    return next(task[name] for name in ASSERT_MODULES if name in task)


def _roots_assert_module() -> dict:
    (module,) = [
        _assert_module(task)
        for task in _assert_tasks()
        if "RUNNER_WORKTREE_ROOTS" in str(_assert_module(task)["that"])
    ]
    return module


def _assert_variables(flavor: str, roots: list[str], src_dir: str) -> dict:
    flavors = render.role_vars()["RUNNER_FLAVORS"]
    declared = (
        {
            **render.flavor_variables(flavor),
            "RUNNER_SRC_DIR": render.source_dir(flavor, src_dir),
        }
        if flavor in flavors
        else {}
    )
    return {
        "RUNNER_FLAVOR": flavor,
        "RUNNER_FLAVORS": flavors,
        "RUNNER_WORKTREE_ROOTS": roots,
        "RUNNER_QUEUE_DIR": render.QUEUE,
        "RUNNER_TOOLCHAIN_IMAGE": render.TOOLCHAIN,
        "RUNNER_OPERATOR_UID": render.OPERATOR,
        "RUNNER_OPERATOR_GID": render.OPERATOR,
        **declared,
    }


def _holds(clauses: list[str], variables: dict) -> bool:
    return all(render.condition(clause, **variables) for clause in clauses)


def _accepted(flavor: str, roots: list[str], src_dir: str = render.SRC_DIR) -> bool:
    return _passes(_assert_variables(flavor, roots, src_dir))


def _queue_accepted(flavor: str, queue: object) -> bool:
    variables = _assert_variables(flavor, render.ROOTS, render.SRC_DIR)
    return _passes({**variables, "RUNNER_QUEUE_DIR": queue})


def _passes(variables: dict) -> bool:
    return all(
        not _holds(_clauses(task), variables)
        or _holds(_assert_module(task)["that"], variables)
        for task in _assert_tasks()
    )


class TestGithubFlavor(unittest.TestCase):
    def test_the_role_defaults_to_the_github_flavor(self) -> None:
        self.assertEqual(render.runner_defaults()["flavor"], "github")
        self.assertEqual(render.runner_defaults()["worktree_roots"], [])
        role_vars = render.role_vars()
        self.assertIn("'services.runner.flavor'", role_vars["RUNNER_FLAVOR"])
        self.assertIn(
            "'services.runner.worktree_roots'", role_vars["RUNNER_WORKTREE_ROOTS"]
        )

    def test_the_fixture_carries_the_sentinels_this_test_feeds(self) -> None:
        fixture = render.fixture()
        self.assertEqual(
            render.env_values(fixture["instance_env"])["RUNNER_API_TOKEN"], render.PAT
        )
        self.assertEqual(
            render.env_values(fixture["test_env"])["GITHUB_TOKEN"], render.PAT
        )
        self.assertEqual(
            render.env_values(fixture["test_env"])["RUNNER_GIT_REF"], render.GIT_REF
        )

    def test_every_render_is_byte_identical_to_today(self) -> None:
        self.assertEqual(render.renders("github"), render.fixture())

    def test_an_inventory_without_the_key_renders_today(self) -> None:
        self.assertEqual(render.renders(render.flavor_of({})), render.fixture())

    def test_a_template_that_leaks_the_mounts_breaks_the_identity(self) -> None:
        source = read_text(str(render.ROLE / "templates" / render.COMPOSE)).replace(
            "RUNNER_MOUNTS_WORKTREES | bool", "true", 1
        )
        self.assertNotEqual(
            source, read_text(str(render.ROLE / "templates" / render.COMPOSE))
        )
        leaked = render.render(render.COMPOSE, "github", source=source)
        self.assertNotEqual(leaked, render.fixture()["compose"])

    def test_the_local_flavor_differs_from_today(self) -> None:
        local = render.renders("local")
        changed = sorted(
            key for key, text in local.items() if text != render.fixture()[key]
        )
        self.assertEqual(
            changed,
            ["compose", "compose_swarm", "entrypoint", "instance_env", "test_env"],
        )


class TestLocalFlavor(unittest.TestCase):
    def test_it_renders_no_registration(self) -> None:
        local = render.env_values(render.render(render.INSTANCE_ENV, "local"))
        github = render.env_values(render.render(render.INSTANCE_ENV, "github"))
        self.assertEqual([key for key in REGISTRATION_KEYS if key in local], [])
        self.assertEqual([key for key in REGISTRATION_KEYS if key not in github], [])
        entrypoint = render.staged_entrypoint("local")
        self.assertEqual(
            [call for call in REGISTRATION_CALLS if call in entrypoint], []
        )
        self.assertEqual(
            [
                call
                for call in REGISTRATION_CALLS
                if call not in render.staged_entrypoint("github")
            ],
            [],
        )

    def test_it_renders_no_pat(self) -> None:
        local = render.renders("local")
        self.assertEqual([key for key, text in local.items() if render.PAT in text], [])
        github = render.renders("github")
        self.assertEqual(
            sorted(key for key, text in github.items() if render.PAT in text),
            ["instance_env", "test_env"],
        )

    def test_it_renders_no_checkout(self) -> None:
        local = render.renders("local")
        self.assertEqual(
            [key for key, text in local.items() if render.GIT_REF in text], []
        )
        test_env = render.env_values(local["test_env"])
        self.assertEqual([key for key in CHECKOUT_KEYS if key in test_env], [])
        github_env = render.env_values(render.renders("github")["test_env"])
        self.assertEqual(github_env["RUNNER_GIT_REF"], render.GIT_REF)

    def test_it_fetches_no_github_runner_binary(self) -> None:
        tasks = _binary_tasks()
        self.assertEqual(len(tasks), 4, [name for name, _when in tasks])
        stat = {"stat": {"exists": False}}
        for name, when in tasks:
            with self.subTest(task=name):
                self.assertFalse(
                    render.condition(
                        when,
                        **render.flavor_variables("local"),
                        _runner_binary_stat=stat,
                    )
                )
                self.assertTrue(
                    render.condition(
                        when,
                        **render.flavor_variables("github"),
                        _runner_binary_stat=stat,
                    )
                )

    def test_it_mounts_every_worktree_root_read_only_at_its_host_path(self) -> None:
        for swarm in (False, True):
            with self.subTest(swarm=swarm):
                local = render.render(render.COMPOSE, "local", swarm=swarm)
                for name, mounts in _root_mounts(local, render.ROOTS).items():
                    self.assertEqual(
                        sorted(mounts),
                        sorted(f"{root}:{root}:ro" for root in render.ROOTS),
                        name,
                    )
                github = render.render(render.COMPOSE, "github", swarm=swarm)
                self.assertEqual(
                    {name: [] for name in _services(github)},
                    _root_mounts(github, render.ROOTS),
                )

    def test_the_mounts_follow_the_configured_roots(self) -> None:
        roots = ["/srv/checkouts"]
        local = render.render(render.COMPOSE, "local", roots=roots)
        self.assertEqual(
            {name: [f"{roots[0]}:{roots[0]}:ro"] for name in _services(local)},
            _root_mounts(local, roots),
        )
        self.assertEqual(
            {name: [] for name in _services(local)},
            _root_mounts(local, render.ROOTS),
        )

    def test_it_keeps_the_per_instance_dind_environment(self) -> None:
        local = render.env_values(render.render(render.INSTANCE_ENV, "local"))
        github = render.env_values(render.render(render.INSTANCE_ENV, "github"))
        self.assertEqual(
            {key: local[key] for key in INSTANCE_KEYS},
            {key: github[key] for key in INSTANCE_KEYS},
        )
        self.assertEqual(local["INFINITO_SUBNET"], "172.30.1.0/24")


class TestFlavorValidation(unittest.TestCase):
    def test_every_flavor_ships_its_entrypoint(self) -> None:
        flavors = render.role_vars()["RUNNER_FLAVORS"]
        self.assertEqual(sorted(flavors), ["github", "local"])
        for flavor, declared in flavors.items():
            with self.subTest(flavor=flavor):
                path = declared["entrypoint"]
                self.assertTrue((render.ROLE / "files" / path).is_file(), path)

    def test_every_flavor_declares_the_same_capabilities(self) -> None:
        flavors = render.role_vars()["RUNNER_FLAVORS"]
        self.assertEqual(
            {flavor: sorted(flavors["github"]) for flavor in flavors},
            {flavor: sorted(declared) for flavor, declared in flavors.items()},
        )

    def test_the_known_flavors_pass_the_assert(self) -> None:
        self.assertTrue(_accepted("github", []))
        self.assertTrue(_accepted("local", render.ROOTS))

    def test_a_local_flavor_without_roots_is_refused(self) -> None:
        self.assertFalse(_accepted("local", []))

    def test_an_unknown_flavor_is_refused(self) -> None:
        self.assertFalse(_accepted("gitlab", render.ROOTS))

    def test_the_flavor_refusal_names_every_known_flavor(self) -> None:
        message = (
            render.environment()
            .from_string(_assert_module(_assert_tasks()[0])["fail_msg"])
            .render(**_assert_variables("gitlab", render.ROOTS, "/srv/core"))
        )
        self.assertIn("'gitlab'", message)
        self.assertIn("github, local", message)


class TestLocalSourceDir(unittest.TestCase):
    def test_the_local_flavor_takes_its_configured_checkout_never_the_deploys(
        self,
    ) -> None:
        self.assertEqual(render.source_dir("local"), render.SRC_DIR)
        self.assertNotEqual(render.source_dir("local"), render.PLAYBOOK)
        self.assertNotIn(
            "playbook_dir", read_text(str(render.ROLE / ROLE_FILE_DEFAULTS_MAIN))
        )
        self.assertEqual(render.source_dir("github"), render.IMAGE_SRC_DIR)

    def test_an_unset_checkout_is_refused_naming_the_key_and_where_to_set_it(
        self,
    ) -> None:
        variables = _assert_variables("local", render.ROOTS, "")
        self.assertFalse(_passes(variables))
        (module,) = [
            _assert_module(task)
            for task in _assert_tasks()
            if "RUNNER_TOOLCHAIN_IMAGE" in str(_assert_module(task)["that"])
        ]
        message = (
            render.environment().from_string(module["fail_msg"]).render(**variables)
        )
        self.assertIn("services.runner.src_dir", message)
        self.assertIn("INFINITO_RUNNER_SRC_DIR", message)

    def test_no_image_and_root_as_the_operator_are_refused(self) -> None:
        variables = _assert_variables("local", render.ROOTS, render.SRC_DIR)
        self.assertTrue(_passes(variables))
        for changed in (
            {"RUNNER_TOOLCHAIN_IMAGE": ""},
            {"RUNNER_OPERATOR_UID": 0},
            {"RUNNER_OPERATOR_GID": ""},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(_passes({**variables, **changed}))
        self.assertTrue(
            _passes({**_assert_variables("github", [], ""), "RUNNER_OPERATOR_UID": ""})
        )

    def test_a_local_runner_runs_the_toolchain_image_as_the_operator(self) -> None:
        for name, service in _services(render.render(render.COMPOSE, "local")).items():
            with self.subTest(service=name):
                self.assertEqual(
                    [service["image"], service["user"], "build" in service],
                    [render.TOOLCHAIN, f"{render.OPERATOR}:{render.OPERATOR}", False],
                )
                self.assertEqual(
                    service["entrypoint"],
                    [
                        "bash",
                        f"{render.SRC_DIR}/roles/svc-runner/files/shell/entrypoint-local.sh",
                    ],
                )
        for service in _services(render.render(render.COMPOSE, "github")).values():
            self.assertNotIn("user", service)
        local = render.env_values(render.render(render.INSTANCE_ENV, "local"))
        self.assertEqual(local[loop.IMAGE_KEY], render.TOOLCHAIN)

    def test_a_local_runner_carries_no_health_check_that_never_passes(self) -> None:
        for swarm in (False, True):
            local = render.render(render.COMPOSE, "local", swarm=swarm)
            github = render.render(render.COMPOSE, "github", swarm=swarm)
            with self.subTest(swarm=swarm):
                self.assertEqual(
                    {
                        name: (service.get("healthcheck") or {}).get("test")
                        for name, service in _services(local).items()
                    },
                    dict.fromkeys(_services(local), HEALTHCHECK_DISABLED),
                )
                self.assertEqual(
                    [
                        name
                        for name, service in _services(github).items()
                        if (service.get("healthcheck") or {}).get("test")
                        == HEALTHCHECK_DISABLED
                    ],
                    [],
                )

    def test_the_default_checkout_passes_the_assert(self) -> None:
        self.assertTrue(_accepted("local", render.ROOTS))
        self.assertTrue(_accepted("local", [f"{render.ROOTS[1]}/"]))
        self.assertTrue(_accepted("local", render.ROOTS, render.ROOTS[0]))
        self.assertTrue(_accepted("local", [render.SRC_DIR]))

    def test_a_local_checkout_outside_every_root_is_refused(self) -> None:
        for src_dir in (
            render.IMAGE_SRC_DIR,
            f"{render.ROOTS[0]}-other/core",
            "/srv/core",
        ):
            with self.subTest(src_dir=src_dir):
                self.assertFalse(_accepted("local", render.ROOTS, src_dir))

    def test_the_github_flavor_keeps_the_image_checkout(self) -> None:
        self.assertTrue(_accepted("github", [], "/srv/core"))

    def test_the_refusal_names_the_checkout_and_every_root(self) -> None:
        message = (
            render.environment()
            .from_string(_roots_assert_module()["fail_msg"])
            .render(**_assert_variables("local", render.ROOTS, "/srv/core"))
        )
        self.assertIn("/srv/core", message)
        self.assertIn(json.dumps(render.ROOTS), message)

    def test_every_malformed_root_list_is_refused(self) -> None:
        for roots in (
            "/nowhere:/else",
            [],
            [""],
            ["/"],
            ["//"],
            ["home"],
            [None],
            [f"{render.ROOTS[1]}/../../.."],
            {render.ROOTS[1]: True},
        ):
            with self.subTest(roots=roots):
                self.assertFalse(_accepted("local", roots, render.SRC_DIR))

    def test_a_root_that_holds_a_home_directory_or_a_colon_is_refused(self) -> None:
        for root in (
            render.HOME,
            f"{render.HOME}/",
            render.HOME.replace("/home/", "/home//"),
            "/home",
            "/root",
            "/Users/operator",
            "/Users",
            f"/var{render.HOME}",
            "/var",
            f"{render.ROOTS[1]}:/srv",
            "/srv/a:b",
        ):
            with self.subTest(root=root):
                self.assertFalse(_accepted("local", [render.ROOTS[1], root]))

    def test_a_checkout_that_climbs_out_of_its_root_is_refused(self) -> None:
        climbing = f"{render.ROOTS[1]}/../../../../srv/core"
        self.assertFalse(_accepted("local", render.ROOTS, climbing))


def _queue_mounts(text: str) -> dict[str, list[str]]:
    wanted = f"{render.QUEUE}:{render.QUEUE}"
    return {
        name: [volume for volume in service["volumes"] if volume == wanted]
        for name, service in _services(text).items()
    }


class TestLocalJobQueue(unittest.TestCase):
    def test_every_local_runner_mounts_the_queue_writable_at_its_host_path(
        self,
    ) -> None:
        for swarm in (False, True):
            with self.subTest(swarm=swarm):
                local = render.render(render.COMPOSE, "local", swarm=swarm)
                github = render.render(render.COMPOSE, "github", swarm=swarm)
                self.assertEqual(
                    _queue_mounts(local),
                    {
                        name: [f"{render.QUEUE}:{render.QUEUE}"]
                        for name in _services(local)
                    },
                )
                self.assertEqual(
                    _queue_mounts(github), {name: [] for name in _services(github)}
                )

    def test_a_local_runner_knows_its_queue_and_the_checkout_whose_loop_it_runs(
        self,
    ) -> None:
        local = render.env_values(render.render(render.INSTANCE_ENV, "local"))
        github = render.env_values(render.render(render.INSTANCE_ENV, "github"))
        self.assertEqual(
            [local["INFINITO_RUNNER_QUEUE_DIR"], local["RUNNER_SRC_DIR"]],
            [render.QUEUE, render.SRC_DIR],
        )
        self.assertEqual([key for key in QUEUE_ENV_KEYS if key in github], [])

    def test_a_local_runner_copies_each_job_below_its_own_install_dir(self) -> None:
        local = render.env_values(render.render(render.INSTANCE_ENV, "local"))
        values = render.variables("local", False, render.ROOTS)
        own = f"{values['RUNNER_INSTALL_DIR']}/{values['runner_instance']}"
        self.assertEqual(local[loop.CHECKOUT_KEY], f"{own}/checkout")
        self.assertIn(loop.CHECKOUT_KEY, loop.RUNNER_ONLY)
        self.assertIn(loop.CHECKOUT_KEY, QUEUE_ENV_KEYS)
        for name, service in _services(render.render(render.COMPOSE, "local")).items():
            instance = name.rsplit("-", 1)[1]
            mount = f"{values['RUNNER_INSTALL_DIR']}/{instance}"
            with self.subTest(service=name):
                self.assertIn(f"{mount}:{mount}", service["volumes"])

    def test_the_local_entrypoint_runs_the_pool_loop_with_the_queue_env(
        self,
    ) -> None:
        code, calls = _local_entrypoint({})
        self.assertEqual(code, 0)
        (call,) = calls
        self.assertEqual(call["argv"], ["-m", "cli.administration.deploy.pool.serve"])
        self.assertEqual(call["cwd"], call["src"])
        self.assertEqual(call["pythonpath"], call["src"])

    def test_the_local_entrypoint_refuses_to_start_without_its_queue_env(
        self,
    ) -> None:
        for key in ("COMPOSE_PROJECT_NAME", *QUEUE_ENV_KEYS):
            with self.subTest(key=key):
                code, calls = _local_entrypoint({key: None})
                self.assertNotEqual(code, 0)
                self.assertEqual(calls, [])

    def test_a_local_runner_needs_an_absolute_queue(self) -> None:
        self.assertTrue(_queue_accepted("local", render.QUEUE))
        for queue in ("", "jobs", "/", "//", f"{render.QUEUE}/../..", "/a:b", None):
            with self.subTest(queue=queue):
                self.assertFalse(_queue_accepted("local", queue))

    def test_the_github_flavor_needs_no_queue(self) -> None:
        self.assertTrue(_queue_accepted("github", ""))


def _queue_task(module: str, key: str, value: str) -> tuple[int, dict]:
    return next(
        (index, task)
        for index, task in enumerate(_tasks(QUEUE_TASKS))
        if (task.get(module) or {}).get(key) == value
    )


def _include(name: str) -> tuple[int, dict]:
    return next(
        (position, task)
        for position, task in enumerate(_tasks(CORE_TASKS))
        if task.get("include_tasks") == name
    )


def _provision_index() -> int:
    return _include(INSTANCE_TASKS)[0]


def _socket_vars() -> dict[str, str]:
    raw = render.role_vars()
    socket = (
        render.environment()
        .from_string(raw["RUNNER_QUEUE_SOCKET"])
        .render(RUNNER_QUEUE_DIR=render.QUEUE)
    )
    return {
        "RUNNER_QUEUE_SOCKET": socket,
        "RUNNER_QUEUE_SOCKET_UNIT": raw["RUNNER_QUEUE_SOCKET_UNIT"],
        "RUNNER_QUEUE_GROUP": role.QUEUE_USER,
    }


def _unit(dest: str) -> configparser.ConfigParser:
    _index, task = _queue_task(TEMPLATE_MODULE, "dest", dest)
    text = read_text(str(render.ROLE / "templates" / task[TEMPLATE_MODULE]["src"]))
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(render.environment().from_string(text).render(_socket_vars()))
    return parser


class TestSharedJobQueue(unittest.TestCase):
    def test_every_local_runner_joins_the_queue_group_and_no_github_runner_does(
        self,
    ) -> None:
        for swarm in (False, True):
            for flavor, joined in (("local", True), ("github", False)):
                text = render.render(render.COMPOSE, flavor, swarm=swarm)
                services = _services(text)
                with self.subTest(swarm=swarm, flavor=flavor):
                    self.assertEqual(
                        {
                            name: str(render.QUEUE_GID)
                            in [str(gid) for gid in service["group_add"]]
                            for name, service in services.items()
                        },
                        dict.fromkeys(services, joined),
                    )

    def test_a_local_runner_knows_the_roots_a_jobs_checkout_must_lie_in(
        self,
    ) -> None:
        local = render.env_values(render.render(render.INSTANCE_ENV, "local"))
        github = render.env_values(render.render(render.INSTANCE_ENV, "github"))
        self.assertEqual(local[loop.ROOTS_KEY], ":".join(render.ROOTS))
        self.assertNotIn(loop.ROOTS_KEY, github)
        self.assertIn(loop.ROOTS_KEY, loop.RUNNER_ONLY)

    def test_the_role_creates_the_queue_for_its_group_only_before_the_runners(
        self,
    ) -> None:
        index, queue = _queue_task("file", "path", "{{ RUNNER_QUEUE_DIR }}")
        group_index, _group = _queue_task("group", "gid", "{{ RUNNER_QUEUE_GID }}")
        include_index, include = _include(QUEUE_TASKS)
        self.assertEqual(
            {key: queue["file"][key] for key in ("state", "owner", "group", "mode")},
            {
                "state": "directory",
                "owner": "root",
                "group": "{{ RUNNER_QUEUE_GID }}",
                "mode": f"{store.QUEUE_ROOT_MODE:o}",
            },
        )
        self.assertEqual(int(queue["file"]["mode"], 8) & 0o007, 0)
        self.assertTrue(int(queue["file"]["mode"], 8) & stat.S_ISVTX)
        self.assertLess(group_index, index)
        self.assertEqual(include["when"], "RUNNER_TAKES_LOCAL_JOBS | bool")
        self.assertLess(include_index, _provision_index())

    def test_the_role_creates_the_queue_folders_shared_below_the_sticky_root(
        self,
    ) -> None:
        root, _queue = _queue_task("file", "path", "{{ RUNNER_QUEUE_DIR }}")
        index, folders = _queue_task(
            "file", "path", "{{ [RUNNER_QUEUE_DIR, item] | path_join }}"
        )
        self.assertEqual(folders["loop"], list(store.QUEUE_DIRS))
        self.assertEqual(
            {key: folders["file"][key] for key in ("state", "owner", "group", "mode")},
            {
                "state": "directory",
                "owner": "root",
                "group": "{{ RUNNER_QUEUE_GID }}",
                "mode": f"{store.SHARED_DIR_MODE:o}",
            },
        )
        self.assertEqual(int(folders["file"]["mode"], 8) & 0o007, 0)
        self.assertNotIn("when", folders)
        self.assertLess(root, index)

    def test_the_queue_group_is_its_own_and_the_queue_code_names_it(self) -> None:
        users = load_yaml_any(str(render.ROLE / ROLE_FILE_META_USERS))
        self.assertEqual(users[role.QUEUE_USER]["gid"], render.QUEUE_GID)
        self.assertNotEqual(
            users[role.QUEUE_USER]["gid"], render.runner_account()["gid"]
        )
        self.assertIn(f"'{role.QUEUE_USER}'", render.role_vars()["RUNNER_QUEUE_GID"])


class TestQueueSocket(unittest.TestCase):
    def test_the_socket_lies_in_the_queue_where_the_pool_commands_look(self) -> None:
        socket = _socket_vars()["RUNNER_QUEUE_SOCKET"]
        self.assertEqual(socket, f"{render.QUEUE}/{role.DOCKER_SOCKET}")
        self.assertEqual(role.docker_host(Path(render.QUEUE)), f"unix://{socket}")

    def test_only_the_queue_group_reaches_the_daemon_on_it(self) -> None:
        self.assertEqual(
            dict(_unit("{{ RUNNER_QUEUE_SOCKET_UNIT_FILE }}")["Socket"]),
            {
                "ListenStream": f"{render.QUEUE}/{role.DOCKER_SOCKET}",
                "SocketMode": "0660",
                "SocketUser": "root",
                "SocketGroup": role.QUEUE_USER,
                "Service": "docker.service",
            },
        )

    def test_the_daemon_takes_the_queue_socket_beside_its_own(self) -> None:
        self.assertEqual(
            _unit("{{ RUNNER_DOCKER_DROPIN }}")["Service"]["Sockets"].split(),
            ["docker.socket", _socket_vars()["RUNNER_QUEUE_SOCKET_UNIT"]],
        )

    def test_only_the_local_flavor_opens_it_after_the_queue_before_the_runners(
        self,
    ) -> None:
        index, include = _include(QUEUE_TASKS)
        folders, _task = _queue_task(
            "file", "path", "{{ [RUNNER_QUEUE_DIR, item] | path_join }}"
        )
        unit, _unit_task = _queue_task(
            TEMPLATE_MODULE, "dest", "{{ RUNNER_QUEUE_SOCKET_UNIT_FILE }}"
        )
        self.assertEqual(
            [
                render.condition(include["when"], RUNNER_TAKES_LOCAL_JOBS=local)
                for local in (True, False)
            ],
            [True, False],
        )
        self.assertLess(folders, unit)
        self.assertLess(index, _provision_index())

    def test_a_changed_unit_restarts_the_socket_and_then_the_daemon(self) -> None:
        restart = _tasks(QUEUE_TASKS)[-1]
        self.assertEqual(
            restart["loop"], ["{{ RUNNER_QUEUE_SOCKET_UNIT }}", "docker.service"]
        )
        self.assertEqual(
            restart["ansible.builtin.systemd_service"]["state"], "restarted"
        )
        for unit, dropin in ((False, False), (True, False), (False, True)):
            with self.subTest(unit=unit, dropin=dropin):
                self.assertEqual(
                    render.condition(
                        restart["when"],
                        _runner_queue_socket_unit=SimpleNamespace(changed=unit),
                        _runner_queue_socket_dropin=SimpleNamespace(changed=dropin),
                    ),
                    unit or dropin,
                )


if __name__ == "__main__":
    unittest.main()
