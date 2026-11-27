from __future__ import annotations

import unittest

from plugins.filter.resource_filter import resource_filter
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VOLUMES

APPLICATION_ID = "web-app-semaphore"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
SERVICES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
VOLUMES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))
STACK_HOST_ROLE = "manager"


def bind_services(volumes=VOLUMES):
    """Args:
    volumes: the parsed ``meta/volumes.yml``.

    Returns:
        ``{service: [volume, ...]}`` of every service that mounts a host bind
        source, which the deploy writes on the stack host alone.
    """
    services = {}
    for name, entry in volumes.items():
        if entry.get("type") != "bind" or entry.get("swarm_safe") is False:
            continue
        for mount in entry.get("mounts") or []:
            services.setdefault(mount["service"], []).append(name)
    return services


def placement_findings(services=SERVICES, volumes=VOLUMES):
    """Args:
    services: the parsed ``meta/services.yml``.
    volumes: the parsed ``meta/volumes.yml``.

    Returns:
        Every service with a host bind source whose swarm task the
        ``deploy.yml.j2`` placement lets run off the stack host.
    """
    applications = {APPLICATION_ID: {"services": services}}
    return [
        f"{service} mounts {', '.join(names)} but swarm may place it on any node"
        for service, names in sorted(bind_services(volumes).items())
        if resource_filter(applications, APPLICATION_ID, "placement", service, "")
        != STACK_HOST_ROLE
    ]


class TestBindPlacement(unittest.TestCase):
    def test_the_provision_runner_mounts_the_catalogs_bind(self):
        self.assertIn(
            "semaphore_provision_catalogs", bind_services()["provision-runner"]
        )

    def test_every_bind_mounting_service_runs_on_the_stack_host(self):
        self.assertEqual(placement_findings(), [])

    def test_negative_control_an_unpinned_provision_runner_is_reported(self):
        services = {
            name: {key: value for key, value in entry.items() if key != "placement"}
            if name == "provision-runner"
            else entry
            for name, entry in SERVICES.items()
        }
        self.assertEqual(
            placement_findings(services),
            [
                (
                    "provision-runner mounts semaphore_provision_catalogs "
                    "but swarm may place it on any node"
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
