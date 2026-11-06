from __future__ import annotations

import json
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-dashboard"
TEMPLATE = ROLE / "templates" / "nginx" / "sso.html.conf.j2"
STATUS_FILE = "/var/lib/infinito/health/status.json"
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))


def _render(*, status: bool) -> str:
    """Render the dashboard's extra vhost locations.

    Args:
        status: the value of ``DASHBOARD_STATUS_ENABLED``.
    """
    templar = Templar(
        loader=DataLoader(),
        variables={
            "DASHBOARD_STATUS_ENABLED": status,
            "DASHBOARD_STATUS_PATH": VARS["DASHBOARD_STATUS_PATH"],
            "DASHBOARD_STATUS_FILE": STATUS_FILE,
            "DASHBOARD_LOCATION_SILENT_CHECK": VARS["DASHBOARD_LOCATION_SILENT_CHECK"],
        },
    )
    return templar.template(
        trust_as_template(read_text(str(TEMPLATE))), overrides={"trim_blocks": True}
    )


def _block(config: str, head: str) -> str:
    """Return the body of the location block that opens with ``head``.

    Args:
        config: the rendered locations.
        head: the text between ``location`` and the opening brace.
    """
    match = re.search(rf"location {re.escape(head)} \{{(.*?)\n\}}", config, re.DOTALL)
    if match is None:
        raise AssertionError(f"no location {head} in:\n{config}")
    return match.group(1)


class TestStatusLocation(unittest.TestCase):
    def test_the_dashboard_serves_the_sweep_document_on_its_own_vhost(self):
        status = _block(_render(status=True), "= /status.json")

        self.assertEqual(VARS["DASHBOARD_STATUS_PATH"], "/status.json")
        self.assertIn(f"alias {STATUS_FILE};", status)
        self.assertIn("default_type application/json;", status)
        self.assertIn("expires -1;", status)

    def test_a_missing_document_answers_with_an_empty_one_instead_of_a_404(self):
        config = _render(status=True)

        self.assertIn(
            "error_page 404 = @dashboard_status_empty;",
            _block(config, "= /status.json"),
        )
        fallback = _block(config, "@dashboard_status_empty")
        body = re.search(r"return 200 '(.*)';", fallback)
        self.assertIsNotNone(body, fallback)
        self.assertEqual(
            json.loads(body.group(1)), {"generated": None, "applications": {}}
        )
        self.assertIn("default_type application/json;", fallback)

    def test_the_status_locations_keep_the_server_level_headers(self):
        config = _render(status=True)

        for head in ("= /status.json", "@dashboard_status_empty"):
            self.assertNotIn("add_header", _block(config, head), head)

    def test_switching_the_badges_off_removes_the_status_location(self):
        config = _render(status=False)

        self.assertNotIn("/status.json", config)
        self.assertNotIn("@dashboard_status_empty", config)
        self.assertIn(
            "postMessage",
            _block(config, f"= {VARS['DASHBOARD_LOCATION_SILENT_CHECK']}"),
        )


if __name__ == "__main__":
    unittest.main()
