"""The MCP adapter's build context is staged exactly when compose renders it.

svc-stack stages ``<instance>/mcp`` while ``services.<mcp.endpoint.service_key>.enabled``
holds; the compose template renders that service while ``NEXTCLOUD_MCP_ENABLED``
holds. A build context compose renders but svc-stack never staged fails
``compose build`` (fork run 43777013536, job 0_Batch_Nextcloud_0).
"""

from __future__ import annotations

import re
import unittest

from utils.cache.applications import get_merged_applications
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_VARS_MAIN
from utils.tests.caches import fresh_caches

ROLE = "roles/web-app-nextcloud"
APPLICATION_ID = "web-app-nextcloud"
ROLE_VARS = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_VARS_MAIN))
MCP = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_META_MCP))
RENDER_SERVICE = re.search(
    r"'services\.([a-z_]+)\.enabled'", ROLE_VARS["NEXTCLOUD_MCP_ENABLED"]
).group(1)
STAGE_SERVICE = MCP["endpoint"]["service_key"]


def _services(applications: dict) -> dict:
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar

    variables = {"group_names": [APPLICATION_ID], "applications": applications}
    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)
    with fresh_caches(files_changed=False):
        merged = get_merged_applications(variables=variables, templar=templar)
    return merged[APPLICATION_ID]


def _override(context_agent: bool, mcp: bool | None = None) -> dict:
    override: dict = {
        "services": {
            RENDER_SERVICE: {"enabled": context_agent, "shared": context_agent}
        }
    }
    if mcp is not None:
        override["mcp"] = {"enabled": mcp, "shared": mcp}
    return {APPLICATION_ID: override}


class TestContextAgentAdapterFlag(unittest.TestCase):
    def test_variant_that_forces_the_context_agent_stages_its_adapter(self):
        nextcloud = _services(_override(context_agent=True))
        self.assertIs(nextcloud["mcp"]["enabled"], False)
        self.assertIs(nextcloud["services"][RENDER_SERVICE]["enabled"], True)
        self.assertIs(nextcloud["services"][STAGE_SERVICE]["enabled"], True)

    def test_mcp_without_the_context_agent_stages_no_adapter(self):
        nextcloud = _services(_override(context_agent=False, mcp=True))
        self.assertIs(nextcloud["mcp"]["enabled"], True)
        self.assertIs(nextcloud["services"][RENDER_SERVICE]["enabled"], False)
        self.assertIs(nextcloud["services"][STAGE_SERVICE]["enabled"], False)


if __name__ == "__main__":
    unittest.main()
