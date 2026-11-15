from __future__ import annotations

import unittest

import jinja2
from ansible.module_utils.parsing.convert_bool import boolean

from plugins.filter.resource_filter import resource_filter
from plugins.filter.swarm.restart_condition import swarm_restart_condition
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

TEMPLATE = PROJECT_ROOT / "roles/svc-net-tor" / ROLE_FILE_TEMPL_COMPOSE
SERVICES = load_yaml_any(
    str(PROJECT_ROOT / "roles/svc-net-tor" / ROLE_FILE_META_SERVICES)
)
APPLICATIONS = {"svc-net-tor": {"services": SERVICES}}
ROLE_DEFAULT_DELAY = "10s"


class _ProjectLoader(jinja2.BaseLoader):
    def get_source(self, environment, template):
        path = PROJECT_ROOT / template
        return read_text(str(path)), str(path), lambda: True


def _lookup(name: str, *terms, **_kwargs):
    if name == "applications":
        return APPLICATIONS
    if name == "compose_replicas":
        return "mode: global" if terms and terms[0] == "global" else "replicas: 1"
    if name == "compose_restart":
        return "restart: unless-stopped"
    if name == "roles_with_placement":
        return []
    return ""


def render(swarm: bool = True) -> str:
    """
    Args:
        swarm: render for swarm mode, else for compose mode.

    Returns:
        The rendered stack file.
    """
    environment = jinja2.Environment(
        loader=_ProjectLoader(),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=jinja2.select_autoescape(default_for_string=False),
    )
    environment.filters.update(
        {
            "bool": boolean,
            "resource_filter": resource_filter,
            "swarm_restart_condition": swarm_restart_condition,
            "abs_role_path_by_application_id": lambda application_id: (
                f"roles/{application_id}"
            ),
            "has_env": lambda _application_id: False,
        }
    )
    environment.globals.update({"lookup": _lookup, "query": lambda *_a, **_k: []})
    return environment.from_string(read_text(str(TEMPLATE))).render(
        application_id="svc-net-tor",
        compose_mode="swarm" if swarm else "compose",
        IS_SWARM_MODE=swarm,
        IS_COMPOSE_MODE=not swarm,
        groups={},
        RUNTIME="local",
        DOCKER_RESTART_POLICY="unless-stopped",
        RESOURCE_CPUS="1",
        RESOURCE_HOST_CPUS="8",
        RESOURCE_MEM_LIMIT="1g",
        RESOURCE_MEM_RESERVATION="256m",
        RESOURCE_PIDS_LIMIT="512",
        SANDBOX_NODE_LABEL="kata-capable",
        service_update_delay=ROLE_DEFAULT_DELAY,
        TOR_IMAGE="debian",
        TOR_VERSION="13.7-slim",
        TOR_FLAVOR="public",
        TOR_CONTAINER="tor",
        TOR_ENTRYPOINT_PATH="/entrypoint",
        TOR_HEALTHCHECK_PATH="/healthcheck",
        TOR_EGRESS_ROUTE="onion",
        TOR_EGRESS_SOCKET_GID=9050,
    )


def update_config(rendered: str) -> list[str]:
    lines = rendered.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "update_config:")
    indent = len(lines[start]) - len(lines[start].lstrip())
    block = []
    for line in lines[start + 1 :]:
        if len(line) - len(line.lstrip()) <= indent:
            break
        block.append(line.strip())
    return block


class TestRollingUpdate(unittest.TestCase):
    def test_the_tor_service_runs_one_task_per_node(self) -> None:
        self.assertIn("mode: global", render())

    def test_each_node_follows_the_last_one_without_a_stagger(self) -> None:
        block = update_config(render())
        self.assertIn("delay: 0s", block)
        self.assertNotIn(f"delay: {ROLE_DEFAULT_DELAY}", block)

    def test_the_rollout_still_replaces_one_node_at_a_time(self) -> None:
        block = update_config(render())
        self.assertIn("parallelism: 1", block)
        self.assertIn("failure_action: continue", block)
        self.assertFalse([line for line in block if line.startswith("order:")])

    def test_compose_mode_renders_no_rollout(self) -> None:
        self.assertNotIn("update_config:", render(swarm=False))


if __name__ == "__main__":
    unittest.main()
