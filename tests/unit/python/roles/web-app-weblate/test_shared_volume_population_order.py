from __future__ import annotations

import json
import unittest

from jinja2 import DictLoader, Environment, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_TEMPL_COMPOSE

ROLE = PROJECT_ROOT / "roles" / "web-app-weblate"
COMPOSE = ROLE / ROLE_FILE_TEMPL_COMPOSE
VOLUMES = ROLE / ROLE_FILE_META_VOLUMES
POPULATING_SERVICE = "beat"
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
}


def _lookup(name, *_terms, extra=None, **_kwargs):
    if name == "container_depends_on" and extra:
        return "depends_on: " + json.dumps(extra)
    return ""


def rendered_services() -> dict[str, dict]:
    """
    Returns:
        The services of the rendered compose file, each with the ``depends_on``
        its ``container_depends_on`` lookup adds beyond the shared ones.
    """
    env = Environment(
        loader=DictLoader({**INCLUDES, "compose.yml.j2": read_text(str(COMPOSE))}),
        autoescape=select_autoescape(default_for_string=False),
    )
    env.globals["lookup"] = _lookup
    return load_yaml_str(env.get_template("compose.yml.j2").render())["services"]


class TestSharedVolumePopulationOrder(unittest.TestCase):
    def test_every_other_sharer_waits_for_the_service_that_fills_the_volume(
        self,
    ) -> None:
        volumes = load_yaml_str(read_text(str(VOLUMES)))
        sharers = {
            mount["service"]
            for entry in volumes.values()
            for mount in entry.get("mounts") or []
        }
        services = rendered_services()
        for service in sorted(sharers - {POPULATING_SERVICE}):
            self.assertIn(
                POPULATING_SERVICE,
                services[service].get("depends_on") or {},
                f"docker fills a fresh named volume from the image once per container "
                f"create and the copy's mkdir is not EEXIST-safe, so '{service}' must "
                f"depend on '{POPULATING_SERVICE}' instead of being created beside it, "
                f"or the deploy dies on 'mkdir /var/lib/docker/volumes/weblate_data/"
                f"_data/python: file exists'",
            )


if __name__ == "__main__":
    unittest.main()
