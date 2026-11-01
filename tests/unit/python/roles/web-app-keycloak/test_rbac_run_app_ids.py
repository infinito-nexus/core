import importlib.util
import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_RBAC, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-keycloak"
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
RBAC = load_yaml_any(str(ROLE / ROLE_FILE_META_RBAC))


def _filter_module(name):
    spec = importlib.util.spec_from_file_location(
        name, str(ROLE / "filter_plugins" / f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rbac_app_ids = _filter_module("rbac_per_app").rbac_app_ids
build_realm_rbac_groups = _filter_module(
    "build_realm_rbac_groups"
).build_realm_rbac_groups


def run_app_ids(running):
    """Render ``KEYCLOAK_RBAC_RUN_APP_IDS`` for one deployment.

    Args:
        running: the ``running`` apps the ``deployment`` lookup reports.
    """
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters["rbac_app_ids"] = rbac_app_ids
    env.globals["lookup"] = lambda name: {"running": running}
    return env.from_string(VARS["KEYCLOAK_RBAC_RUN_APP_IDS"]).render(
        application_id=VARS["application_id"]
    )


class TestRbacRunAppIds(unittest.TestCase):
    def test_an_update_of_another_app_still_runs_keycloak(self):
        self.assertEqual(
            run_app_ids(["web-app-wordpress"]),
            ["web-app-keycloak", "web-app-wordpress"],
        )

    def test_a_run_naming_keycloak_lists_it_once(self):
        self.assertEqual(
            run_app_ids(["web-app-keycloak", "web-app-wordpress"]),
            ["web-app-keycloak", "web-app-wordpress"],
        )

    def test_the_realm_groups_cover_every_console_grant(self):
        paths = {
            group["path"]
            for group in build_realm_rbac_groups(
                {
                    "web-app-keycloak": {"rbac": RBAC},
                    "web-app-wordpress": {"rbac": {}},
                },
                {},
                "roles",
                run_app_ids(["web-app-wordpress"]),
            )
        }
        for role in VARS["KEYCLOAK_CONSOLE_ROLE_GRANTS"]:
            self.assertIn(f"roles/web-app-keycloak/{role}", paths)


if __name__ == "__main__":
    unittest.main()
