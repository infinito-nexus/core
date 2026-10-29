from __future__ import annotations

import unittest

from jinja2 import Environment, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

TEMPLATE = read_text(
    str(PROJECT_ROOT / "roles/web-app-nextcloud" / ROLE_FILE_TEMPL_COMPOSE)
)


def _environment(deployment_mode: str) -> dict:
    start = TEMPLATE.index("    environment:\n")
    end = TEMPLATE.index("    sysctls:", start)
    rendered = (
        Environment(autoescape=select_autoescape(default_for_string=False))
        .from_string(TEMPLATE[start:end])
        .render(DEPLOYMENT_MODE=deployment_mode)
    )
    return load_yaml_str(rendered)["environment"]


class TestServerId(unittest.TestCase):
    def test_compose_pins_a_server_id_nextcloud_accepts(self):
        server_id = int(_environment("compose")["NC_serverid"])
        self.assertGreaterEqual(server_id, 1)
        self.assertLessEqual(server_id, 511)

    def test_swarm_gives_every_replica_its_task_slot(self):
        environment = _environment("swarm")
        self.assertEqual(environment["NC_serverid"], "{{.Task.Slot}}")
        self.assertEqual(environment["TASK_SLOT"], "{{.Task.Slot}}")


if __name__ == "__main__":
    unittest.main()
