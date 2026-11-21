from __future__ import annotations

import importlib
import json
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str

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


def _assert_variables(flavor: str, roots: list[str], playbook_dir: str) -> dict:
    flavors = render.role_vars()["RUNNER_FLAVORS"]
    declared = (
        {
            **render.flavor_variables(flavor),
            "RUNNER_SRC_DIR": render.source_dir(flavor, playbook_dir),
        }
        if flavor in flavors
        else {}
    )
    return {
        "RUNNER_FLAVOR": flavor,
        "RUNNER_FLAVORS": flavors,
        "RUNNER_WORKTREE_ROOTS": roots,
        **declared,
    }


def _holds(clauses: list[str], variables: dict) -> bool:
    return all(render.condition(clause, **variables) for clause in clauses)


def _accepted(
    flavor: str, roots: list[str], playbook_dir: str = render.PLAYBOOK_DIR
) -> bool:
    variables = _assert_variables(flavor, roots, playbook_dir)
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
    def test_the_local_flavor_takes_the_checkout_the_deploy_runs_from(self) -> None:
        self.assertEqual(render.source_dir("local"), render.PLAYBOOK_DIR)
        self.assertEqual(render.source_dir("github"), render.IMAGE_SRC_DIR)

    def test_the_default_checkout_passes_the_assert(self) -> None:
        self.assertTrue(_accepted("local", render.ROOTS))
        self.assertTrue(_accepted("local", [f"{render.ROOTS[1]}/"]))
        self.assertTrue(_accepted("local", render.ROOTS, render.ROOTS[0]))
        self.assertTrue(_accepted("local", [render.PLAYBOOK_DIR]))

    def test_a_local_checkout_outside_every_root_is_refused(self) -> None:
        for playbook_dir in (
            render.IMAGE_SRC_DIR,
            f"{render.ROOTS[0]}-other/core",
            "/srv/core",
        ):
            with self.subTest(playbook_dir=playbook_dir):
                self.assertFalse(_accepted("local", render.ROOTS, playbook_dir))

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
                self.assertFalse(_accepted("local", roots, render.PLAYBOOK_DIR))

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


if __name__ == "__main__":
    unittest.main()
