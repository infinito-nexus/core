from __future__ import annotations

import unittest

import jinja2

from plugins.filter.resource_filter import resource_filter
from plugins.filter.swarm.restart_condition import swarm_restart_condition
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.variant.services import _merged_services
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

SERVICES_PATH = PROJECT_ROOT / "roles/svc-net-tor" / ROLE_FILE_META_SERVICES
VARIANTS_PATH = PROJECT_ROOT / "roles/svc-net-tor" / ROLE_FILE_META_VARIANTS
TEMPLATES = PROJECT_ROOT / "roles/sys-svc-container/templates"


def services(flavor: str | None) -> dict:
    """
    Args:
        flavor: the variant whose tor.flavor matches, None for meta/services.yml alone.

    Returns:
        The services map the round resolver hands the role.
    """
    if flavor is None:
        return load_yaml_any(str(SERVICES_PATH))
    variants = load_yaml_any(str(VARIANTS_PATH))
    for index, variant in enumerate(variants):
        if variant["services"]["tor"]["flavor"] == flavor:
            return _merged_services(SERVICES_PATH, index, variant["services"])
    raise AssertionError(f"no variant runs the {flavor} flavor")


def render(template: str, flavor: str | None) -> list[str]:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        trim_blocks=True,
        autoescape=jinja2.select_autoescape(default_for_string=False),
    )
    environment.filters.update(
        {
            "resource_filter": resource_filter,
            "swarm_restart_condition": swarm_restart_condition,
        }
    )
    applications = {"svc-net-tor": {"services": services(flavor)}}

    def _lookup(name: str, *terms, **_kwargs):
        if name == "applications":
            return applications
        if name == "compose_replicas":
            return "mode: global" if terms and terms[0] == "global" else "replicas: 1"
        if name in ("roles_with_placement", "gpu"):
            return []
        raise AssertionError(f"unexpected lookup: {name}")

    environment.globals["lookup"] = _lookup
    rendered = environment.get_template(template).render(
        compose_mode="swarm",
        application_id="svc-net-tor",
        service_name="tor",
        groups={},
        RUNTIME="local",
        DOCKER_RESTART_POLICY="unless-stopped",
        RESOURCE_CPUS="1",
        RESOURCE_HOST_CPUS="8",
        RESOURCE_MEM_LIMIT="1g",
        RESOURCE_MEM_RESERVATION="256m",
        RESOURCE_PIDS_LIMIT="512",
    )
    return [" ".join(line.split()) for line in rendered.splitlines()]


def swarm_memory(flavor: str | None) -> dict[str, str]:
    lines = render("deploy.yml.j2", flavor)
    limits, reservations = lines.index("limits:"), lines.index("reservations:")
    return {
        "limit": next(line for line in lines[limits:] if line.startswith("memory:")),
        "reservation": next(
            line for line in lines[reservations:] if line.startswith("memory:")
        ),
    }


class TestResourceBooking(unittest.TestCase):
    def test_production_books_the_public_footprint(self) -> None:
        self.assertEqual(
            swarm_memory(None), {"limit": "memory: 256m", "reservation": "memory: 64m"}
        )

    def test_the_public_variant_books_the_public_footprint(self) -> None:
        self.assertEqual(
            swarm_memory("public"),
            {"limit": "memory: 256m", "reservation": "memory: 64m"},
        )

    def test_the_chutney_variant_books_its_measured_peak(self) -> None:
        self.assertEqual(
            swarm_memory("chutney"),
            {"limit": "memory: 2g", "reservation": "memory: 512m"},
        )

    def test_compose_mode_reserves_what_swarm_books(self) -> None:
        for flavor, reservation in (
            (None, "64m"),
            ("public", "64m"),
            ("chutney", "512m"),
        ):
            with self.subTest(flavor=flavor):
                self.assertIn(
                    f"mem_reservation: {reservation}", render("resource.yml.j2", flavor)
                )


if __name__ == "__main__":
    unittest.main()
