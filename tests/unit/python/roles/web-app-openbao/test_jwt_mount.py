from __future__ import annotations

import base64
import unittest
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
SEMAPHORE_ORIGIN = "https://semaphore.example.test"
CA_PEM = "-----BEGIN CERTIFICATE-----\nMIIBdeploymentCA\n-----END CERTIFICATE-----\n"


def role_vars() -> dict[str, Any]:
    return load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))


def tasks(name: str) -> list[dict[str, Any]]:
    return load_yaml_any(str(ROLE_DIR / "tasks" / name))


def task_named(name: str, fragment: str) -> dict[str, Any]:
    return next(task for task in tasks(name) if fragment in task.get("name", ""))


def fake_lookup(kind: str, application: str, key: str) -> str:
    if (kind, application, key) != ("tls", "web-app-semaphore", "url.origin"):
        raise AssertionError(f"unexpected lookup {kind}, {application}, {key}")
    return SEMAPHORE_ORIGIN


def render(text: str, **context: Any) -> str:
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["b64decode"] = lambda value: base64.b64decode(value).decode()
    environment.filters["bool"] = bool
    environment.globals["lookup"] = fake_lookup
    return environment.from_string(text).render(**context)


def jwt_config(tls_mode: str) -> dict[str, str]:
    """
    Args:
        tls_mode: the deployment's ``TLS_MODE``.

    Returns:
        The body every task token mount's ``config`` is written with.
    """
    values = role_vars()
    issuer = render(values["OPENBAO_JWT_ISSUER"])
    context = {
        "OPENBAO_JWT_ISSUER": issuer,
        "OPENBAO_JWT_JWKS_URL": render(
            values["OPENBAO_JWT_JWKS_URL"], OPENBAO_JWT_ISSUER=issuer
        ),
        "OPENBAO_JWT_CA_REQUIRED": render(
            values["OPENBAO_JWT_CA_REQUIRED"], TLS_MODE=tls_mode
        )
        == "True",
        "openbao_jwt_ca": {"content": base64.b64encode(CA_PEM.encode()).decode()},
    }
    return {
        key: render(value, **context)
        for key, value in values["OPENBAO_JWT_CONFIG"].items()
    }


class TestTheJwtMount(unittest.TestCase):
    def test_the_jwt_mount_trusts_the_semaphore_key_set(self) -> None:
        self.assertEqual(
            jwt_config("self_signed"),
            {
                "jwks_url": f"{SEMAPHORE_ORIGIN}/.well-known/jwks.json",
                "bound_issuer": SEMAPHORE_ORIGIN,
                "jwks_ca_pem": CA_PEM,
            },
        )

    def test_a_public_certificate_needs_no_deployment_ca(self) -> None:
        self.assertEqual(jwt_config("letsencrypt")["jwks_ca_pem"], "")

    def test_both_task_token_mounts_get_that_configuration(self) -> None:
        task = task_named("07_workspaces.yml", "Point the task token mounts")
        self.assertEqual(task["loop"], "{{ OPENBAO_JWT_MOUNTS }}")
        self.assertEqual(task["args"]["stdin"], "{{ OPENBAO_JWT_CONFIG | to_json }}")
        self.assertIn("p=auth/{{ item }}/config", task["ansible.builtin.shell"])
        self.assertEqual(
            role_vars()["OPENBAO_JWT_MOUNTS"],
            ["{{ OPENBAO_JWT_MOUNT }}", "{{ OPENBAO_JWT_EXPORT_MOUNT }}"],
        )

    def test_the_mounts_are_jwt_auth_methods(self) -> None:
        task = task_named("07_workspaces.yml", "task token auth mounts")
        self.assertEqual(task["loop"], "{{ OPENBAO_JWT_MOUNTS }}")
        self.assertIn(
            "bao auth enable -path={{ item | quote }} jwt",
            task["ansible.builtin.shell"],
        )

    def test_the_ca_is_read_only_under_self_signed(self) -> None:
        task = task_named("07_workspaces.yml", "deployment CA")
        self.assertEqual(
            task["ansible.builtin.slurp"]["src"], "{{ CA_TRUST.cert_host }}"
        )
        self.assertEqual(task["when"], "OPENBAO_JWT_CA_REQUIRED | bool")

    def test_the_mounts_exist_only_beside_a_deployed_semaphore(self) -> None:
        include = task_named("01_init.yml", "workspace mounts")
        self.assertEqual(
            include["ansible.builtin.include_tasks"]["file"], "07_workspaces.yml"
        )
        self.assertEqual(include["when"], "OPENBAO_WORKSPACES_ENABLED | bool")
        self.assertIn(
            "services.semaphore.enabled", role_vars()["OPENBAO_WORKSPACES_ENABLED"]
        )


if __name__ == "__main__":
    unittest.main()
