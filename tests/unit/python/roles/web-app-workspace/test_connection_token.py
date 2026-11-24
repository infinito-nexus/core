from __future__ import annotations

import copy
import functools
import json
import re
import unittest
from typing import TYPE_CHECKING, Any

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.filter.core import to_bool
from ansible.template import Templar
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.lookup.container_volumes import container_volumes
from utils.cache.applications import (
    get_merged_applications,
    get_variant_overrides_only,
)
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.reset import _reset_cache_for_tests
from utils.cache.yaml import load_yaml, load_yaml_any, load_yaml_str
from utils.roles.applications.services.sso import get_sso_config
from utils.roles.applications.status_codes import declared_status_codes
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

if TYPE_CHECKING:
    from collections.abc import Callable

APPLICATION_ID = "web-app-workspace"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
DOCKERFILE = ROLE / "files" / "Dockerfile"
ENV_TEMPLATE = ROLE / "templates" / "env.j2"
CORE_TASKS = ROLE / "tasks" / "00_core.yml"
TOKEN_TEMPLATE = "connection-token.j2"
TOKEN_FLAGS = {"--connection-token", "--connection-token-file"}
NO_TOKEN_FLAG = "--without-connection-token"
TOKEN_FREE_PATHS = {"version"}
TOKEN_REFUSAL = 403
HEAD_REFUSAL = 405
IMAGE_USER = 1000
IMAGE_PROGRAMS = {"curl", "wget"}
RESOLVED = (
    "WORKSPACE_SSO_PROXY_GATED",
    "WORKSPACE_UID",
    "WORKSPACE_GID",
    "WORKSPACE_PORT_INTERNAL",
    "WORKSPACE_DATA_DIR",
    "WORKSPACE_CONNECTION_TOKEN_FILE",
    "WORKSPACE_READY_PATH",
)
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
    "roles/sys-svc-container/templates/env.j2": "",
}


def stub_lookup(gated: bool) -> Callable[..., Any]:
    """
    Args:
        gated: what ``lookup('sso', APPLICATION_ID, 'is_proxy_gated')`` returns.

    Returns:
        A ``lookup`` that reads ``config`` and ``volume`` from the role's own
        meta files and answers every other plugin with an empty string.
    """
    services = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))
    volumes = load_yaml(str(ROLE / ROLE_FILE_META_VOLUMES))

    def lookup(plugin: str, *terms: Any, **_kwargs: Any) -> Any:
        if plugin == "sso" and terms == (APPLICATION_ID, "is_proxy_gated"):
            return gated
        if plugin == "volume" and terms[:1] == (APPLICATION_ID,):
            entry = volumes[terms[1]]
            return {**entry, "target": entry["mounts"][0]["target"]}
        if plugin == "config" and terms[:1] == (APPLICATION_ID,):
            value: Any = {"services": services}
            for key in str(terms[1]).split("."):
                value = value[key]
            return value
        return ""

    return lookup


def environment(gated: bool) -> Environment:
    """
    Args:
        gated: whether the OAuth2 proxy fronts the editor.

    Returns:
        A strict Jinja environment with the role's lookups stubbed.
    """
    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    env.filters["bool"] = to_bool
    env.filters["to_json"] = json.dumps
    env.filters["dotenv_quote"] = str
    env.globals["lookup"] = stub_lookup(gated)
    return env


def resolved_vars(gated: bool) -> dict[str, Any]:
    """
    Args:
        gated: whether the OAuth2 proxy fronts the editor.

    Returns:
        The ``RESOLVED`` names of ``vars/main.yml``, rendered.
    """
    env = environment(gated)
    declared = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
    return {
        name: env.from_string(declared[name]).render(application_id=APPLICATION_ID)
        for name in RESOLVED
    }


def render(path: Any, gated: bool, **extra: Any) -> str:
    """
    Args:
        path: the role template to render.
        gated: whether the OAuth2 proxy fronts the editor.
        extra: template variables beyond the resolved ``vars/main.yml``.

    Returns:
        The rendered template.
    """
    return (
        environment(gated)
        .from_string(read_text(str(path)))
        .render(
            application_id=APPLICATION_ID,
            WORKSPACE_BUILD_DIR="/opt/compose/workspace",
            WORKSPACE_BASE_IMAGE="gitpod/openvscode-server",
            WORKSPACE_BASE_VERSION="1.99.3",
            WORKSPACE_CONTAINER="workspace",
            SANDBOX_RUNTIME="kata",
            DOCKER_BIND_HOST="127.0.0.1",
            **resolved_vars(gated),
            **extra,
        )
    )


def workspace_service(gated: bool) -> dict[str, Any]:
    return load_yaml_str(render(ROLE / ROLE_FILE_TEMPL_COMPOSE, gated))["services"][
        "workspace"
    ]


def mounts(gated: bool) -> dict[str, Any]:
    env = environment(gated)
    out = container_volumes(
        {APPLICATION_ID: {}},
        APPLICATION_ID,
        "workspace",
        render_jinja=lambda expr: env.from_string(expr).render(),
    )
    return load_yaml_str(out) if out else {}


def token_render_task() -> dict[str, Any]:
    for task in load_yaml_any(str(CORE_TASKS)):
        templates = (task.get("vars") or {}).get("role_templates") or []
        if any(entry.get("src") == TOKEN_TEMPLATE for entry in templates):
            return task
    raise AssertionError(f"no task renders {TOKEN_TEMPLATE}")


def rendered(group_names: list[str], override: dict[str, Any]) -> dict[str, Any]:
    """
    Args:
        group_names: the groups of the host.
        override: the inventory's ``applications`` entry of the role, the
            variant overlay in the matrix, {} for none.

    Returns:
        The role's configuration as ``get_merged_applications`` renders it
        with a real Ansible templar.
    """
    applications = {APPLICATION_ID: copy.deepcopy(override)} if override else {}
    variables = {"group_names": list(group_names), "applications": applications}
    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)
    _reset_cache_for_tests()
    try:
        return get_merged_applications(variables=variables, templar=templar)[
            APPLICATION_ID
        ]
    finally:
        _reset_cache_for_tests()


@functools.cache
def deployments() -> dict[str, dict[str, Any]]:
    """
    Returns:
        ``{name: configuration}`` of the role on a host with and without
        Keycloak, and in every matrix variant on a host with Keycloak.
    """
    keycloak = [APPLICATION_ID, "web-app-keycloak"]
    resolved = {
        "host with keycloak": rendered(keycloak, {}),
        "host without keycloak": rendered([APPLICATION_ID], {}),
    }
    overrides = get_variant_overrides_only(roles_dir=PROJECT_ROOT / "roles")
    for index, override in enumerate(overrides[APPLICATION_ID]):
        resolved[f"variant {index}"] = rendered(keycloak, override)
    return resolved


def proxy_gated(configuration: dict[str, Any]) -> bool:
    """
    Args:
        configuration: a rendered configuration of the role.

    Returns:
        What ``lookup('sso', APPLICATION_ID, 'is_proxy_gated')`` answers for it.
    """
    return get_sso_config({APPLICATION_ID: configuration}, APPLICATION_ID)[
        "is_proxy_gated"
    ]


def entrypoint(dockerfile: str) -> list[str] | None:
    """
    Args:
        dockerfile: Dockerfile text.

    Returns:
        The exec-form argv of its last ENTRYPOINT, or None when it inherits the
        base image's.
    """
    lines = [line for line in dockerfile.splitlines() if line.startswith("ENTRYPOINT ")]
    return json.loads(lines[-1].split(" ", 1)[1]) if lines else None


class TestTheProxyIsTheAuthentication(unittest.TestCase):
    def test_a_proxied_editor_starts_without_a_connection_token(self):
        command = workspace_service(gated=True)["command"]
        self.assertIn(NO_TOKEN_FLAG, command)
        self.assertFalse(
            TOKEN_FLAGS & set(command),
            f"openvscode-server exits 1 when a token flag comes with {NO_TOKEN_FLAG}",
        )

    def test_an_unproxied_editor_reads_the_token_file(self):
        values = resolved_vars(gated=False)
        command = workspace_service(gated=False)["command"]
        self.assertNotIn(NO_TOKEN_FLAG, command)
        self.assertEqual(
            command[command.index("--connection-token-file") + 1],
            values["WORKSPACE_CONNECTION_TOKEN_FILE"],
        )

    def test_the_token_file_is_mounted_only_without_the_proxy(self):
        self.assertNotIn("secrets", mounts(gated=True))
        self.assertEqual(
            mounts(gated=False)["secrets"],
            [
                {
                    "source": "workspace_connection_token",
                    "target": resolved_vars(gated=False)[
                        "WORKSPACE_CONNECTION_TOKEN_FILE"
                    ],
                    "uid": str(IMAGE_USER),
                    "gid": str(IMAGE_USER),
                    "mode": 0o400,
                }
            ],
        )

    def test_the_host_token_file_is_written_only_without_the_proxy(self):
        when = token_render_task()["when"]
        condition = environment(gated=False).compile_expression(when)
        self.assertTrue(condition(WORKSPACE_SSO_PROXY_GATED=False))
        self.assertFalse(condition(WORKSPACE_SSO_PROXY_GATED=True))

    def test_the_token_reaches_the_env_only_without_the_proxy(self):
        extra = {
            "WORKSPACE_CONNECTION_TOKEN": "fixture",
            "WORKSPACE_ISOLATION": load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))[
                "workspace"
            ]["isolation"],
        }
        self.assertNotIn(
            "WORKSPACE_CONNECTION_TOKEN=",
            render(ENV_TEMPLATE, gated=True, **extra),
        )
        self.assertIn(
            "WORKSPACE_CONNECTION_TOKEN=fixture",
            render(ENV_TEMPLATE, gated=False, **extra),
        )

    def test_the_editor_port_is_published_on_the_bind_host_only(self):
        compose = read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))
        self.assertEqual(
            re.findall(r"lookup\('container_ports', ([^)]*)\)", compose),
            ["['workspace', 'http', DOCKER_BIND_HOST]"],
            "an ip-bound term stays on loopback in compose and is not "
            "published at all in swarm, so only the proxy reaches the editor",
        )

    def test_the_entrypoint_does_not_switch_the_token_off(self):
        argv = entrypoint(read_text(str(DOCKERFILE)))
        self.assertIsNotNone(
            argv,
            f"the base image's entrypoint passes {NO_TOKEN_FLAG}, and "
            "openvscode-server exits 1 when a token flag comes with it",
        )
        self.assertNotIn(NO_TOKEN_FLAG, " ".join(argv))
        self.assertIn('"$@"', " ".join(argv))


class TestTheEditorRunsAsTheImageUser(unittest.TestCase):
    def test_the_container_user_is_the_image_user(self):
        for gated in (True, False):
            self.assertEqual(
                workspace_service(gated)["user"], f"{IMAGE_USER}:{IMAGE_USER}"
            )

    def test_the_host_token_file_belongs_to_the_image_user(self):
        values = resolved_vars(gated=False)
        env = environment(gated=False)
        (entry,) = token_render_task()["vars"]["role_templates"]
        self.assertEqual(
            (
                env.from_string(entry["owner"]).render(**values),
                env.from_string(entry["group"]).render(**values),
            ),
            (str(IMAGE_USER), str(IMAGE_USER)),
        )

    def test_tmp_is_a_tmpfs_every_user_can_write(self):
        self.assertIn(
            {"type": "tmpfs", "target": "/tmp", "tmpfs": {"mode": 0o1777}},
            mounts(gated=True)["volumes"],
        )

    def test_the_root_filesystem_stays_read_only_without_capabilities(self):
        service = workspace_service(gated=True)
        self.assertIs(service["read_only"], True)
        self.assertEqual(service["cap_drop"], ["ALL"])


class TestTheProbes(unittest.TestCase):
    def test_the_probes_use_an_unauthenticated_path(self):
        ready_path = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))["prometheus"].get(
            "ready_path", ""
        )
        self.assertIn(
            ready_path,
            TOKEN_FREE_PATHS,
            "openvscode-server answers every other path without the token with "
            "403, so /healthz/ready never reports the workspace ready",
        )

    def test_the_healthcheck_runs_a_program_the_image_ships(self):
        test = workspace_service(gated=False)["healthcheck"]["test"]
        self.assertEqual(test[0], "CMD")
        self.assertIn(
            test[1],
            IMAGE_PROGRAMS,
            "the base image has no node on PATH, so a node probe never runs",
        )
        ready_path = resolved_vars(gated=False)["WORKSPACE_READY_PATH"]
        self.assertTrue(test[-1].endswith(f"/{ready_path}"))

    def test_a_host_without_keycloak_runs_the_editor_behind_its_token(self):
        gates = {name: proxy_gated(config) for name, config in deployments().items()}
        self.assertIs(gates["host with keycloak"], True)
        self.assertIs(gates["host without keycloak"], False)
        self.assertEqual(set(gates.values()), {True, False})

    def test_the_rendered_codes_accept_403_exactly_behind_the_token(self):
        for name, configuration in deployments().items():
            command = workspace_service(proxy_gated(configuration))["command"]
            token_gated = bool(TOKEN_FLAGS & set(command))
            codes = configuration["server"]["status_codes"]["default"]
            with self.subTest(deployment=name, token_gated=token_gated):
                self.assertIsInstance(codes, list)
                self.assertIn(HEAD_REFUSAL, codes)
                self.assertEqual(
                    TOKEN_REFUSAL in codes,
                    token_gated,
                    "openvscode-server refuses GET / without the token with 403; "
                    "behind the proxy a 403 is a refusal the probes must report",
                )
                self.assertEqual(
                    declared_status_codes(
                        {APPLICATION_ID: configuration}, APPLICATION_ID, ""
                    ),
                    codes,
                )


if __name__ == "__main__":
    unittest.main()
