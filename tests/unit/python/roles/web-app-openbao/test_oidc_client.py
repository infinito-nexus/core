from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
OIDC_TASKS = ROLE_DIR / "tasks/utils/oidc.yml"
AUDIENCE = "bound_audiences={{ OPENBAO_OIDC_CLIENT_ID | quote }}"


def oidc_role_script() -> str:
    scripts = [
        str(task.get("ansible.builtin.shell", ""))
        for task in load_yaml_any(str(OIDC_TASKS))
        if "auth/oidc/role/" in str(task.get("ansible.builtin.shell", ""))
    ]
    if len(scripts) != 1:
        raise AssertionError(
            f"expected one task writing the OIDC role, found {len(scripts)}"
        )
    return scripts[0]


class TestTheOwnClient(unittest.TestCase):
    def test_the_oidc_role_accepts_only_tokens_for_its_own_client(self) -> None:
        self.assertIn(AUDIENCE, oidc_role_script())

    def test_client_id_and_secret_come_from_the_role_itself(self) -> None:
        variables = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertIn(
            "'services.sso.oidc.clients.web'", variables["OPENBAO_OIDC_CLIENT_ID"]
        )
        self.assertIn(
            "'secrets.credentials.oidc_client_secret'",
            variables["OPENBAO_OIDC_CLIENT_SECRET"],
        )
        for name in ("OPENBAO_OIDC_CLIENT_ID", "OPENBAO_OIDC_CLIENT_SECRET"):
            with self.subTest(variable=name):
                self.assertNotIn("OIDC.CLIENT", variables[name])

    def test_the_secret_is_a_sha256_credential(self) -> None:
        secrets = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SECRETS))
        credential = secrets["credentials"]["oidc_client_secret"]
        self.assertEqual(credential["algorithm"], "sha256")
        self.assertEqual(credential["validation"], "^[a-f0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
