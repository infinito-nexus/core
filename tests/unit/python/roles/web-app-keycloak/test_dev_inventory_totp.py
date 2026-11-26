import json
import tempfile
import unittest
from pathlib import Path

from cli.administration.deploy.development.common import DEV_INVENTORY_VARS_FILE
from cli.administration.inventory.provision.host_vars import (
    apply_vars_overrides,
    apply_vars_overrides_from_file,
)
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROOT = Path(PROJECT_ROOT)
VARS_FILE = ROOT / DEV_INVENTORY_VARS_FILE


def _totp_enforced(document: dict) -> object:
    return document["applications"]["web-app-keycloak"]["services"]["keycloak"][
        "realm"
    ]["totp_enforced"]


class TestDevInventorySwitchesTotpEnforcementOff(unittest.TestCase):
    def test_the_dev_vars_file_switches_enforcement_off(self) -> None:
        self.assertIs(False, _totp_enforced(load_yaml_any(str(VARS_FILE))))

    def test_production_keeps_the_enforced_default(self) -> None:
        services = load_yaml_any(
            str(ROOT / "roles/web-app-keycloak" / ROLE_FILE_META_SERVICES)
        )
        self.assertIs(True, services["keycloak"]["realm"]["totp_enforced"])

    def test_provision_carries_the_override_into_host_vars(self) -> None:
        variant_bake = {
            "applications": {
                "web-app-keycloak": {
                    "services": {"keycloak": {"email": {"policy": "external"}}}
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            host_vars = Path(directory) / "localhost.yml"
            apply_vars_overrides_from_file(
                host_vars_file=host_vars, vars_file=VARS_FILE
            )
            apply_vars_overrides(
                host_vars_file=host_vars, json_str=json.dumps(variant_bake)
            )
            self.assertIs(False, _totp_enforced(load_yaml_any(str(host_vars))))


if __name__ == "__main__":
    unittest.main()
