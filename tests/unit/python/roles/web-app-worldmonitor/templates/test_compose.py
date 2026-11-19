from __future__ import annotations

import os
import posixpath
import unittest
import unittest.mock as mock
from pathlib import Path, PurePosixPath

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.lookup.compose_only import LookupModule as ComposeOnlyLookup
from plugins.lookup.container_image import LookupModule as ContainerImageLookup
from plugins.lookup.container_ports import LookupModule as ContainerPortsLookup
from plugins.lookup.image import LookupModule as ImageLookup
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_str
from utils.docker.image.discovery import iter_role_images
from utils.git_refspec import git_refspec
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)
from utils.update.repository import collect_entries as repository_entries

from . import PROJECT_ROOT

APP = "web-app-worldmonitor"
ROLE = PROJECT_ROOT / "roles" / APP
SERVICES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
REDIS_SERVICES = load_yaml_str(
    read_text(str(PROJECT_ROOT / "roles" / "svc-db-redis" / ROLE_FILE_META_SERVICES))
)
VARS = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
CORE_TASKS = load_yaml_str(read_text(str(ROLE / "tasks" / "00_core.yml")))
ROLE_FILES = sorted(
    Path(path) for path in iter_project_files() if path.startswith(f"{ROLE}{os.sep}")
)

CLONE = "/opt/compose/worldmonitor/repository"
BIND_HOST = "127.0.0.1"
REGISTRY = {"host": "registry.example", "port": "5000"}
PREFIX = {"compose": "", "swarm": "registry.example:5000/"}
BUILT = ("worldmonitor", "ais-relay", "redis-rest", "seeder")
UNPUBLISHED = ("ais-relay", "redis-rest", "cache", "seeder")
UPSTREAM_FROM = "node:24-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5"
NODE_CONTEXT = {UPSTREAM_FROM: f"docker-image://node@{SERVICES['node']['version']}"}
BUILD = SERVICES["stack"]["checkout"]["build"]
BUILD_VARS = (
    "WORLDMONITOR_DOCKERFILES",
    "WORLDMONITOR_APP_DOCKERFILE",
    "WORLDMONITOR_RELAY_DOCKERFILE",
    "WORLDMONITOR_REST_CONTEXT",
    "WORLDMONITOR_REST_DOCKERFILE",
    "WORLDMONITOR_NODE_FROM",
    "WORLDMONITOR_NODE_IMAGE",
    "WORLDMONITOR_REF",
)
AUTH_BYPASS_FLAGS = ("I_UNDERSTAND_THIS_DISABLES_AUTH", "ALLOW_UNAUTHENTICATED_RELAY")

INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
}


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer]


def _environment() -> Environment:
    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    env.filters["path_join"] = lambda parts: str(PurePosixPath(*parts))
    env.filters["dirname"] = posixpath.dirname
    env.filters["basename"] = posixpath.basename
    return env


def _evaluate(env: Environment, value: str, context: dict):
    """Evaluate one single-expression ``vars/main.yml`` value to its native type.

    Args:
        env: the environment whose filters and lookup the value uses.
        value: the ``{{ ... }}`` string from ``vars/main.yml``.
        context: the variables the expression reads.

    Returns:
        The value the expression yields.
    """
    expression = value.strip().removeprefix("{{").removesuffix("}}")
    return env.compile_expression(expression)(**context)


def render(mode: str) -> dict:
    """Render the World Monitor compose file with the image and port lookups live.

    Args:
        mode: the deployment mode, ``compose`` or ``swarm``.

    Returns:
        The ``services`` mapping of the rendered compose file.
    """
    variables = {
        "application_id": APP,
        "DEPLOYMENT_MODE": mode,
        "swarm": {"registry": REGISTRY},
    }
    applications = {
        APP: {"services": SERVICES},
        "svc-db-redis": {"services": REDIS_SERVICES},
    }
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "applications":
            return _Stub(applications)
        if name == "image":
            return ImageLookup()
        return real_get(name, *args, **kwargs)

    live = {
        "compose_only": ComposeOnlyLookup,
        "container_image": ContainerImageLookup,
        "container_ports": ContainerPortsLookup,
        "image": ImageLookup,
    }

    def lookup(name, *terms, **kwargs):
        if name in live:
            return live[name]().run(list(terms), variables=variables, **kwargs)[0]
        if name == "config":
            node = applications[terms[0]]
            for part in terms[1].split("."):
                node = node[part]
            return env.from_string(node).render() if isinstance(node, str) else node
        if name == "service_memory_mb":
            return "256"
        return ""

    env = _environment()
    env.globals["lookup"] = lookup
    context = {"application_id": APP, "compose_repository_path": CLONE}
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        for name in BUILD_VARS:
            context[name] = _evaluate(env, VARS[name], context)
        rendered = env.from_string(
            read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))
        ).render(
            **context,
            DOCKER_BIND_HOST=BIND_HOST,
            WORLDMONITOR_SEEDER_TARGET=VARS["WORLDMONITOR_SEEDER_TARGET"],
            WORLDMONITOR_CONTAINER=SERVICES["worldmonitor"]["name"],
            WORLDMONITOR_RELAY_CONTAINER=SERVICES["ais-relay"]["name"],
            WORLDMONITOR_REST_CONTAINER=SERVICES["redis-rest"]["name"],
            WORLDMONITOR_CACHE_CONTAINER=SERVICES["cache"]["name"],
            WORLDMONITOR_SEEDER_CONTAINER=SERVICES["seeder"]["name"],
        )
    return load_yaml_str(rendered)["services"]


class TestPinnedSource(unittest.TestCase):
    def test_the_clone_is_pinned_to_a_full_commit(self) -> None:
        app = SERVICES["worldmonitor"]
        self.assertEqual(app["ref_kind"], "commit")
        self.assertEqual(git_refspec(app["ref"], app["ref_kind"]), app["ref"])
        checkout = SERVICES["stack"]["checkout"]
        self.assertIn("services.worldmonitor.ref", checkout["ref"])
        self.assertIn("services.worldmonitor.repository", checkout["url"])
        self.assertEqual(
            read_text(str(ROLE / "tasks" / "utils" / "stack.yml")),
            read_text(
                str(PROJECT_ROOT / "roles" / "svc-stack" / "files" / "bridge.yml")
            ),
        )
        self.assertFalse(any("include_role" in task for task in CORE_TASKS))

    def test_every_built_image_carries_the_tag_of_the_clone(self) -> None:
        for name in BUILT:
            with self.subTest(service=name):
                self.assertTrue(SERVICES[name]["custom"])
                self.assertNotIn("version", SERVICES[name])
                self.assertNotIn("update", SERVICES[name])

    def test_the_repository_updater_moves_the_commit_pin(self) -> None:
        pins = [
            (entry.entity_path, entry.ref)
            for entry in repository_entries(PROJECT_ROOT)
            if entry.role == APP
        ]
        self.assertEqual(pins, [(("worldmonitor",), SERVICES["worldmonitor"]["ref"])])

    def test_the_image_discovery_lists_the_node_base_by_digest(self) -> None:
        refs = [
            ref
            for ref in iter_role_images(PROJECT_ROOT)
            if ref.role == APP and ref.service == "node"
        ]
        digest = SERVICES["node"]["version"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].version, digest)
        self.assertEqual(refs[0].source, f"docker.io/library/node@{digest}")

    def test_the_only_declared_build_base_is_the_pinned_node_entity(self) -> None:
        self.assertEqual(list(BUILD["bases"]), ["node"])


class TestComposeBuilds(unittest.TestCase):
    def setUp(self) -> None:
        self.services = {mode: render(mode) for mode in PREFIX}

    def test_worldmonitor_builds_the_root_dockerfile_of_the_clone(self) -> None:
        for mode, services in self.services.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    services["worldmonitor"]["build"],
                    {
                        "context": CLONE,
                        "dockerfile": "Dockerfile",
                        "additional_contexts": NODE_CONTEXT,
                    },
                )

    def test_the_other_images_build_from_the_same_clone(self) -> None:
        expected = {
            "ais-relay": {
                "context": CLONE,
                "dockerfile": "Dockerfile.relay",
                "additional_contexts": NODE_CONTEXT,
            },
            "redis-rest": {
                "context": f"{CLONE}/docker",
                "dockerfile": "Dockerfile.redis-rest",
                "additional_contexts": NODE_CONTEXT,
            },
            "seeder": {
                "context": CLONE,
                "dockerfile": "Dockerfile",
                "target": "builder",
                "additional_contexts": NODE_CONTEXT,
            },
        }
        for mode, services in self.services.items():
            for name, build in expected.items():
                with self.subTest(mode=mode, service=name):
                    self.assertEqual(services[name]["build"], build)

    def test_the_base_guard_reads_every_dockerfile_a_build_uses(self) -> None:
        declared = {
            str(PurePosixPath(CLONE, path)) for path in BUILD["dockerfiles"].values()
        }
        for mode, services in self.services.items():
            built = {
                str(PurePosixPath(build["context"], build["dockerfile"]))
                for build in (service.get("build") for service in services.values())
                if build
            }
            with self.subTest(mode=mode):
                self.assertEqual(built, declared)

    def test_every_image_is_the_pinned_local_build(self) -> None:
        version = SERVICES["worldmonitor"]["ref"]
        local = {
            "worldmonitor": "worldmonitor_custom",
            "ais-relay": "worldmonitor-ais-relay_custom",
            "redis-rest": "worldmonitor-redis-rest_custom",
            "seeder": "worldmonitor-seeder_custom",
        }
        for mode, services in self.services.items():
            for name, image in local.items():
                with self.subTest(mode=mode, service=name):
                    self.assertEqual(
                        services[name]["image"], f"{PREFIX[mode]}{image}:{version}"
                    )
        for name in BUILT:
            with self.subTest(service=name):
                self.assertEqual(self.services["compose"][name]["pull_policy"], "never")

    def test_the_role_ships_no_dockerfile_of_its_own(self) -> None:
        self.assertEqual(
            [path for path in ROLE_FILES if path.name.startswith("Dockerfile")], []
        )


class TestPublishedPorts(unittest.TestCase):
    def test_compose_publishes_only_the_dashboard_on_the_bind_host(self) -> None:
        services = render("compose")
        app = SERVICES["worldmonitor"]["ports"]
        self.assertEqual(
            services["worldmonitor"]["ports"],
            [f"{BIND_HOST}:{app['local']['http']}:{app['internal']['http']}"],
        )
        for name in UNPUBLISHED:
            with self.subTest(service=name):
                self.assertNotIn("ports", services[name])

    def test_swarm_publishes_no_port(self) -> None:
        for name, service in render("swarm").items():
            with self.subTest(service=name):
                self.assertNotIn("ports", service)


class TestAuthBypassFlags(unittest.TestCase):
    def test_no_role_file_sets_an_auth_bypass_flag(self) -> None:
        for path in ROLE_FILES:
            if path.name == "README.md":
                continue
            text = read_text(str(path))
            for flag in AUTH_BYPASS_FLAGS:
                with self.subTest(file=str(path.relative_to(ROLE)), flag=flag):
                    self.assertNotIn(flag, text)


if __name__ == "__main__":
    unittest.main()
