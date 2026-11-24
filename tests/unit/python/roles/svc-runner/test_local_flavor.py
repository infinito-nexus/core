from __future__ import annotations

import configparser
import importlib
import json
import stat
import unittest
from pathlib import Path
from types import SimpleNamespace

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_USERS
from utils.runner import jobs, loop, role

render = importlib.import_module("tests.unit.python.roles.svc-runner._render")

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


def _binary_tasks() -> list[tuple[str, str]]:
    tasks = [
        *load_yaml_any(str(render.ROLE / "tasks" / "00_core.yml")),
        *load_yaml_any(str(render.ROLE / "tasks" / "02_instance.yml")),
    ]
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
        for task in load_yaml_any(str(render.ROLE / "tasks" / "00_core.yml"))
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
            "playbook_dir", read_text(str(render.ROLE / "defaults" / "main.yml"))
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
                        name: service.get("healthcheck")
                        for name, service in _services(local).items()
                    },
                    {name: {"disable": True} for name in _services(local)},
                )
                self.assertEqual(
                    [
                        name
                        for name, service in _services(github).items()
                        if (service.get("healthcheck") or {}).get("disable")
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
        flavors = render.role_vars()["RUNNER_FLAVORS"]
        entrypoint = read_text(
            str(render.ROLE / "files" / flavors["local"]["entrypoint"])
        )
        self.assertIn("python3 -m cli.administration.deploy.pool.serve", entrypoint)
        self.assertNotIn("sleep infinity", entrypoint)
        for key in ("COMPOSE_PROJECT_NAME", *QUEUE_ENV_KEYS):
            self.assertIn(f'"${{{key}:?', entrypoint)

    def test_a_local_runner_needs_an_absolute_queue(self) -> None:
        self.assertTrue(_queue_accepted("local", render.QUEUE))
        for queue in ("", "jobs", "/", "//", f"{render.QUEUE}/../..", "/a:b", None):
            with self.subTest(queue=queue):
                self.assertFalse(_queue_accepted("local", queue))

    def test_the_github_flavor_needs_no_queue(self) -> None:
        self.assertTrue(_queue_accepted("github", ""))


def _core_task(module: str, key: str, value: str) -> tuple[int, dict]:
    tasks = load_yaml_any(str(render.ROLE / "tasks" / "00_core.yml"))
    return next(
        (index, task)
        for index, task in enumerate(tasks)
        if (task.get(module) or {}).get(key) == value
    )


def _include(name: str) -> tuple[int, dict]:
    tasks = load_yaml_any(str(render.ROLE / "tasks" / "00_core.yml"))
    return next(
        (position, task)
        for position, task in enumerate(tasks)
        if task.get("include_tasks") == name
    )


def _provision_index() -> int:
    return _include("02_instance.yml")[0]


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


def _unit(template: str) -> configparser.ConfigParser:
    text = read_text(str(render.ROLE / "templates" / template))
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
        index, queue = _core_task("file", "path", "{{ RUNNER_QUEUE_DIR }}")
        _group_index, group = _core_task("group", "gid", "{{ RUNNER_QUEUE_GID }}")
        self.assertEqual(
            {key: queue["file"][key] for key in ("state", "owner", "group", "mode")},
            {
                "state": "directory",
                "owner": "root",
                "group": "{{ RUNNER_QUEUE_GID }}",
                "mode": f"{jobs.QUEUE_ROOT_MODE:o}",
            },
        )
        self.assertEqual(int(queue["file"]["mode"], 8) & 0o007, 0)
        self.assertTrue(int(queue["file"]["mode"], 8) & stat.S_ISVTX)
        for task in (queue, group):
            self.assertEqual(task["when"], "RUNNER_TAKES_LOCAL_JOBS | bool")
        self.assertLess(index, _provision_index())

    def test_the_role_creates_the_queue_folders_shared_below_the_sticky_root(
        self,
    ) -> None:
        root, _queue = _core_task("file", "path", "{{ RUNNER_QUEUE_DIR }}")
        index, folders = _core_task(
            "file", "path", "{{ [RUNNER_QUEUE_DIR, item] | path_join }}"
        )
        self.assertEqual(folders["loop"], list(jobs.QUEUE_DIRS))
        self.assertEqual(
            {key: folders["file"][key] for key in ("state", "owner", "group", "mode")},
            {
                "state": "directory",
                "owner": "root",
                "group": "{{ RUNNER_QUEUE_GID }}",
                "mode": f"{jobs.SHARED_DIR_MODE:o}",
            },
        )
        self.assertEqual(int(folders["file"]["mode"], 8) & 0o007, 0)
        self.assertEqual(folders["when"], "RUNNER_TAKES_LOCAL_JOBS | bool")
        self.assertLess(root, index)
        self.assertLess(index, _provision_index())

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
            dict(_unit("runner-queue-docker.socket.j2")["Socket"]),
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
            _unit("runner-queue-socket.conf.j2")["Service"]["Sockets"].split(),
            ["docker.socket", _socket_vars()["RUNNER_QUEUE_SOCKET_UNIT"]],
        )

    def test_only_the_local_flavor_opens_it_after_the_queue_before_the_runners(
        self,
    ) -> None:
        index, include = _include("05_queue_socket.yml")
        folders, _task = _core_task(
            "file", "path", "{{ [RUNNER_QUEUE_DIR, item] | path_join }}"
        )
        self.assertEqual(
            [
                render.condition(include["when"], RUNNER_TAKES_LOCAL_JOBS=local)
                for local in (True, False)
            ],
            [True, False],
        )
        self.assertLess(folders, index)
        self.assertLess(index, _provision_index())

    def test_a_changed_unit_restarts_the_socket_and_then_the_daemon(self) -> None:
        tasks = load_yaml_any(str(render.ROLE / "tasks" / "05_queue_socket.yml"))
        restart = tasks[-1]
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
