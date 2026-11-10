from __future__ import annotations

import re
import unittest

from jinja2 import ChainableUndefined, Environment, select_autoescape

from plugins.lookup.container_volumes import container_volumes
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "roles/web-app-nextcloud"
APPLICATION_ID = "web-app-nextcloud"
SERVICES = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_META_SERVICES))
VARS = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_VARS_MAIN))
TEMPLATE = read_text(str(PROJECT_ROOT / ROLE / ROLE_FILE_TEMPL_COMPOSE))


def _render_jinja(expression: str) -> str:
    env = Environment(
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.globals["lookup"] = lambda name, *args, **kwargs: f"<{name} {args!r}>"
    env.filters["path_join"] = lambda parts: "/".join(str(part) for part in parts)
    return env.from_string(expression).render()


def _mounts(service: str) -> str:
    return container_volumes(
        {APPLICATION_ID: {"services": SERVICES}},
        APPLICATION_ID,
        service,
        render_jinja=_render_jinja,
    )


def _service_block(service_var: str) -> str:
    start = TEMPLATE.index(f"{{% set service_name = {service_var} %}}")
    following = re.search(r"\{% (set service_name|if|endif)\b", TEMPLATE[start + 1 :])
    end = start + 1 + following.start() if following else len(TEMPLATE)
    return TEMPLATE[start:end]


class TestTaskProcessingWorker(unittest.TestCase):
    def test_service_key_matches_the_vars_spot(self):
        self.assertIn(VARS["NEXTCLOUD_TASKPROCESSING_SERVICE"], SERVICES)

    def test_worker_mounts_exactly_what_cron_mounts(self):
        cron = _mounts(VARS["NEXTCLOUD_CRON_SERVICE"])
        self.assertIn("/var/www/html/", cron)
        self.assertEqual(_mounts(VARS["NEXTCLOUD_TASKPROCESSING_SERVICE"]), cron)

    def test_worker_scales_with_the_swarm_topology(self):
        self.assertNotIn("replicas", SERVICES[VARS["NEXTCLOUD_TASKPROCESSING_SERVICE"]])

    def test_worker_runs_the_command_that_records_its_heartbeat(self):
        block = _service_block("NEXTCLOUD_TASKPROCESSING_SERVICE")
        self.assertIn("taskprocessing:worker -t 60", block)
        self.assertNotIn("background-job:worker", block)

    def test_worker_runs_the_cron_image_as_the_occ_owner(self):
        worker = _service_block("NEXTCLOUD_TASKPROCESSING_SERVICE")
        cron = _service_block("NEXTCLOUD_CRON_SERVICE")
        image = "{{ lookup('container_image', application_id, 'nextcloud') }}"
        self.assertIn(image, cron)
        self.assertIn(image, worker)
        self.assertIn('"su", "{{ NEXTCLOUD_DOCKER_USER }}"', worker)


if __name__ == "__main__":
    unittest.main()
