"""A role that pins itself to a CPU architecture reaches the swarm renderer.

`platform_arch` on a service is only meaningful if
`roles/sys-svc-container/templates/deploy.yml.j2` turns it into a placement
constraint, so the declaration and its consumer are asserted together.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
DEPLOY_TEMPLATE = PROJECT_ROOT / "roles/sys-svc-container/templates/deploy.yml.j2"

DOCKER_ARCHITECTURES = {"x86_64", "aarch64", "armv7l", "ppc64le", "s390x"}


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
        template = read_text(str(DEPLOY_TEMPLATE))
        self.assertIn("platform_arch", template)
        self.assertIn("node.platform.arch ==", template)

    def test_declared_arches_are_docker_values(self) -> None:
        for location, arch in _declared_arches().items():
            with self.subTest(location=location):
                self.assertIn(arch, DOCKER_ARCHITECTURES)

    def test_lmstudio_is_pinned_to_x86(self) -> None:
        arch = _services(ROLES_DIR / "svc-ai-lmstudio").get("lmstudio", {})
        self.assertEqual(arch.get("platform_arch"), "x86_64")


if __name__ == "__main__":
    unittest.main()
