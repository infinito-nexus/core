from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "web-app-nextcloud"
VARS = ROLE / "vars" / "main.yml"
PROVISION = ROLE / "tasks" / "addons" / "integration_openproject_provision.yml"
STATE = ROLE / "tasks" / "addons" / "integration_openproject_state.yml"
SCRIPT = (
    ROLE / "files" / "ruby" / "addons" / "openproject" / "ensure_nextcloud_storage.rb"
)

BUILD_INPUT = "🔎 Build the OpenProject provisioning input"
DIGEST = "🧮 Digest the provisioning sources, inputs and coupling state"


def _flat(tasks: list[dict]) -> list[dict]:
    """Return the tasks in run order, each block followed by its children.

    Args:
      tasks: parsed task list of one task file.
    """
    flat: list[dict] = []
    for task in tasks:
        flat.append(task)
        flat.extend(_flat(task.get("block") or []))
    return flat


def _task(path, name: str) -> dict:
    """Return the task called ``name`` in the task file at ``path``.

    Args:
      path: task file to search.
      name: exact task name.
    """
    matches = [
        task for task in _flat(load_yaml_any(str(path))) if task.get("name") == name
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"{path}: expected one task named {name!r}, found {len(matches)}"
        )
    return matches[0]


class TestOpenProjectRedirectUris(unittest.TestCase):
    def test_network_base_urls_hold_nextcloud_on_every_network(self):
        self.assertEqual(
            load_yaml_any(str(VARS))["NEXTCLOUD_NETWORK_BASE_URLS"],
            "{{ lookup('network_urls', NEXTCLOUD_URL) }}",
        )

    def test_provision_input_passes_every_network_base_url(self):
        provision_input = _task(PROVISION, BUILD_INPUT)["set_fact"][
            "nextcloud_op_provision_input"
        ]
        self.assertIn(
            "'nextcloud_base_urls': NEXTCLOUD_NETWORK_BASE_URLS", provision_input
        )
        self.assertIn("'nextcloud_host': NEXTCLOUD_URL", provision_input)

    def test_redirect_uris_are_registered_for_every_network_base_url(self):
        script = read_text(str(SCRIPT))
        self.assertIn('PROVISION_INPUT.fetch("nextcloud_base_urls")', script)
        registration = re.search(
            r"^redirect_uri = (.*?)\.join\(\"\\n\"\)$",
            script,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(
            registration, "ensure_nextcloud_storage.rb must assign redirect_uri"
        )
        self.assertIn("base_urls.flat_map", registration.group(1))
        self.assertNotIn("File.join(host,", registration.group(1))

    def test_converge_digest_tracks_the_network_base_urls(self):
        digest = _task(STATE, DIGEST)["set_fact"]["nextcloud_op_digest"]
        self.assertIn("'nextcloud_base_urls': NEXTCLOUD_NETWORK_BASE_URLS", digest)


if __name__ == "__main__":
    unittest.main()
