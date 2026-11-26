"""A role that pins itself to a CPU architecture reaches the swarm renderer.

`platform_arch` on a service is only meaningful if
`roles/sys-svc-container/templates/deploy.yml.j2` turns it into a placement
constraint, so the declaration and its consumer are asserted together.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.resource_filter import resource_filter
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
DEPLOY_TEMPLATE = PROJECT_ROOT / "roles/sys-svc-container/templates/deploy.yml.j2"

DOCKER_ARCHITECTURES = {"x86_64", "aarch64", "armv7l", "ppc64le", "s390x"}

APPLICATION_ID = "web-app-example"
PINNED_ARCH = "aarch64"
SERVICES = {
    "example": {"name": "example"},
    "pinned": {"platform_arch": PINNED_ARCH},
}


def _swarm_constraints(service_name: str) -> list[str]:
    """
    Args:
        service_name: the service of ``SERVICES`` whose swarm deploy block is rendered.

    Returns:
        The placement constraints the block renders.
    """
    env = Environment(
        loader=FileSystemLoader(str(DEPLOY_TEMPLATE.parent)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters.update(
        bool=boolean,
        resource_filter=resource_filter,
        swarm_restart_condition=str,
    )
    answers = {
        "applications": {APPLICATION_ID: {"services": SERVICES}},
        "compose_replicas": "replicas: 1",
        "roles_with_placement": [],
    }
    env.globals["lookup"] = lambda name, *_args, **_kwargs: answers[name]
    rendered = env.get_template(DEPLOY_TEMPLATE.name).render(
        RUNTIME="local",
        DOCKER_RESTART_POLICY="unless-stopped",
        RESOURCE_CPUS="1",
        RESOURCE_HOST_CPUS="8",
        RESOURCE_MEM_LIMIT="1g",
        RESOURCE_MEM_RESERVATION="256m",
        RESOURCE_PIDS_LIMIT="512",
        compose_mode="swarm",
        application_id=APPLICATION_ID,
        service_name=service_name,
        groups={},
    )
    lines = [line.strip() for line in rendered.splitlines()]
    return [line[2:] for line in lines if line.startswith("- node.")]


def _services(role_dir: Path) -> dict:
    path = role_dir / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return {}
    data = load_yaml_any(str(path))
    return data if isinstance(data, dict) else {}


def _declared_arches() -> dict[str, str]:
    found: dict[str, str] = {}
    for role_dir in sorted(ROLES_DIR.iterdir()):
        if not role_dir.is_dir():
            continue
        for service_name, service in _services(role_dir).items():
            if not isinstance(service, dict):
                continue
            arch = service.get("platform_arch")
            if arch is not None:
                found[f"{role_dir.name}/{service_name}"] = str(arch)
    return found


class TestPlatformArchConstraint(unittest.TestCase):
    def test_renderer_consumes_platform_arch(self) -> None:
        self.assertEqual(
            _swarm_constraints("pinned"), [f"node.platform.arch == {PINNED_ARCH}"]
        )
        self.assertEqual(_swarm_constraints("example"), [])

    def test_declared_arches_are_docker_values(self) -> None:
        for location, arch in _declared_arches().items():
            with self.subTest(location=location):
                self.assertIn(arch, DOCKER_ARCHITECTURES)


if __name__ == "__main__":
    unittest.main()
