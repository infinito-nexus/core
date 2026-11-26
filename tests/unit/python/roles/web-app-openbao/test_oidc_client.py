from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

APPLICATION_ID = "web-app-openbao"
ROLE_DIR = PROJECT_ROOT / "roles" / APPLICATION_ID
OIDC_TASKS = ROLE_DIR / "tasks/utils/oidc.yml"
AUDIENCE = "bound_audiences={{ OPENBAO_OIDC_CLIENT_ID | quote }}"


def lookups_of(expression: str) -> str:
    """
    Args:
        expression: a variable of ``vars/main.yml``.

    Returns:
        The lookups it renders, each as ``plugin|term|...``; any other variable
        it reads fails the render.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.globals["lookup"] = lambda plugin, *terms: "|".join((plugin, *terms))
    return env.from_string(expression).render(application_id=APPLICATION_ID)


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
        self.assertEqual(
            [
                lookups_of(variables[name])
                for name in ("OPENBAO_OIDC_CLIENT_ID", "OPENBAO_OIDC_CLIENT_SECRET")
            ],
            [
                f"config|{APPLICATION_ID}|services.sso.oidc.clients.web",
                f"config|{APPLICATION_ID}|secrets.credentials.oidc_client_secret",
            ],
        )

    def test_the_secret_is_a_sha256_credential(self) -> None:
        secrets = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SECRETS))
        credential = secrets["credentials"]["oidc_client_secret"]
        self.assertEqual(credential["algorithm"], "sha256")
        self.assertEqual(credential["validation"], "^[a-f0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
