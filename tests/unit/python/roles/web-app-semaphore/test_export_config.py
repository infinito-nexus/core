from __future__ import annotations

import json
import re
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from .files._export_servers import load_task_module
from .files._semaphore_fake import load_project

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
VARS = ROLE / ROLE_FILE_VARS_MAIN
CORE_TASKS = ROLE / "tasks" / "00_core.yml"
GUARD_TASKS = ROLE / "tasks" / "utils" / "stack" / "guard.yml"
STACK_SERVE = PROJECT_ROOT / "roles" / "svc-stack" / "tasks" / "batch" / "serve.yml"
WORKSPACE_TASKS = ROLE / "tasks" / "utils" / "workspace" / "operation.yml"
SERVICES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
KEYCLOAK_SERVICES = load_yaml_str(
    read_text(
        str(PROJECT_ROOT / "roles" / "web-app-keycloak" / ROLE_FILE_META_SERVICES)
    )
)
SEAWEEDFS_SERVICES = load_yaml_str(
    read_text(
        str(PROJECT_ROOT / "roles" / "web-svc-seaweedfs" / ROLE_FILE_META_SERVICES)
    )
)
DEFAULT_AGE = SERVICES["semaphore"]["workspaces"]["export"]["owner_min_age_days"]
RETENTION = KEYCLOAK_SERVICES["keycloak"]["events"]["admin"]["expiration_days"]
AGE_PATH = "services.semaphore.workspaces.export.owner_min_age_days"
RETENTION_PATH = "services.keycloak.events.admin.expiration_days"
SEMAPHORE_SETS = {"SEMAPHORE_JWT", "SEMAPHORE_PROJECT_ID", "SEMAPHORE_TASK_ID"}
SECRET_SOURCE = re.compile(r"secrets\.|_SECRETS\b|password")
ALIAS = "ws-0b6f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4"
EMAIL = {
    "host": "mail.example.org",
    "port": 465,
    "tls": True,
    "auth": True,
    "from": "no-reply@example.org",
    "username": "no-reply@example.org",
    "password": "relay-password",
}


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms, **kwargs)]


def load_export():
    return load_task_module("export")


def templar(age=DEFAULT_AGE, retention=RETENTION, drop=(), email=EMAIL):
    """Args:
    age: ``owner_min_age_days`` of the inventory.
    retention: ``services.keycloak.events.admin.expiration_days``.
    drop: names removed from ``SEMAPHORE_EXPORT_VARIABLES``.
    email: what ``lookup('email', ...)`` answers.

    Returns:
        ``(templar, stubs)``: a templar over the real ``vars/main.yml`` and the
        lookups it answers from.
    """
    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    declared["SEMAPHORE_EXPORT_VARIABLES"] = {
        name: value
        for name, value in declared["SEMAPHORE_EXPORT_VARIABLES"].items()
        if name not in drop
    }
    config = {
        ("web-app-semaphore", AGE_PATH): age,
        ("web-app-keycloak", RETENTION_PATH): retention,
        ("web-svc-seaweedfs", "services.seaweedfs.region"): SEAWEEDFS_SERVICES[
            "seaweedfs"
        ]["region"],
    }
    stubs = {
        "config": _Stub(lambda app, path: config[(app, path)]),
        "domain": _Stub(lambda app: f"{app}.example.org"),
        "tls": _Stub(lambda term, want: f"https://{term}"),
        "email": _Stub(lambda app: email),
    }
    facts = {
        "OIDC": {"CLIENT": {"ISSUER_URL": "https://auth.example.org/realms/main"}},
        "CA_TRUST_CERT_CONTAINER_SELFSIGNED": "/etc/infinito/ca.crt",
        "semaphore_workspace_alias": ALIAS,
    }
    return Templar(loader=DataLoader(), variables={**declared, **facts}), stubs


def stubbed(stubs):
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name in stubs:
            return stubs[name]
        return real_get(name, *args, **kwargs)

    return mock.patch.object(lookup_loader, "get", side_effect=get)


def owner_age_task():
    """Returns:
    The task of ``tasks/utils/stack/guard.yml`` that asserts the owner age.
    """
    tasks = DataLoader().load_from_file(str(GUARD_TASKS), trusted_as_template=True)
    return next(
        task
        for task in tasks
        if "SEMAPHORE_EXPORT_OWNER_MIN_AGE_DAYS"
        in str((task.get("ansible.builtin.assert") or {}).get("that"))
    )


def owner_age_refusals(age, retention=RETENTION, that=None):
    """Args:
    age: ``owner_min_age_days`` of the inventory.
    retention: the admin event retention of the realm.
    that: the clauses to check, those of the real assert when None.

    Returns:
        Every clause the deploy fails on.
    """
    clauses = (
        owner_age_task()["ansible.builtin.assert"]["that"] if that is None else that
    )
    engine, stubs = templar(age=age, retention=retention)
    with stubbed(stubs):
        return [clause for clause in clauses if not engine.evaluate_conditional(clause)]


def export_environment(drop=(), email=EMAIL):
    """Args:
    drop: names removed from ``SEMAPHORE_EXPORT_VARIABLES``.
    email: what ``lookup('email', ...)`` answers.

    Returns:
        The environment ``tasks/utils/workspace/operation.yml`` hands to the export
        template.
    """
    tasks = DataLoader().load_from_file(str(WORKSPACE_TASKS), trusted_as_template=True)
    spec = next(
        task["vars"]["semaphore_workspace_spec"]
        for task in tasks
        if "semaphore_workspace_spec" in (task.get("vars") or {})
    )
    engine, stubs = templar(drop=drop, email=email)
    with stubbed(stubs):
        return engine.template(spec["export"]["environment"])


def export_logins():
    """Returns:
    The block of ``tasks/00_core.yml`` that hands the export logins to OpenBao.
    """
    tasks = DataLoader().load_from_file(str(CORE_TASKS), trusted_as_template=True)
    return next(
        task
        for task in tasks
        if "SEMAPHORE_EXPORT_MAIL_LOGIN" in str(task.get("block"))
    )


def mail_login_task():
    """Returns:
    The task of ``tasks/00_core.yml`` that writes the relay login to OpenBao.
    """
    return next(
        task
        for task in export_logins()["block"]
        if "SEMAPHORE_EXPORT_MAIL_LOGIN" in str(task.get("vars"))
    )


def environment_findings(environment):
    """Args:
    environment: the rendered environment of the export template.

    Returns:
        Every name ``export.py`` requires that neither the survey nor
        Semaphore sets and the environment lacks, and every non-string value.
    """
    survey = {
        name
        for entry in load_project().EXPORT_TEMPLATES
        if entry["name"] == "export"
        for name, _ in entry["survey"]
    }
    needed = set(load_export().REQUIRED_ENV) - survey - SEMAPHORE_SETS
    findings = [
        f"{name} is not set" for name in sorted(needed) if not environment.get(name)
    ]
    findings += [
        f"{name} is no string"
        for name, value in sorted(environment.items())
        if not isinstance(value, str)
    ]
    return findings


def secret_findings(variables):
    """Args:
    variables: ``SEMAPHORE_EXPORT_VARIABLES`` as ``vars/main.yml`` declares it.

    Returns:
        Every variable whose value reads a secret.
    """
    return [
        f"{name} reads a secret"
        for name, raw in sorted(variables.items())
        if SECRET_SOURCE.search(str(raw))
    ]


class TestExportEnvironment(unittest.TestCase):
    def test_the_export_environment_supplies_what_the_survey_and_semaphore_do_not(self):
        environment = export_environment()
        self.assertEqual(environment_findings(environment), [])
        self.assertEqual(environment["WORKSPACE"], ALIAS)
        self.assertEqual(environment["EXPORT_OWNER_MIN_AGE_DAYS"], str(DEFAULT_AGE))
        self.assertEqual(environment["EXPORT_MAIL_PORT"], str(EMAIL["port"]))
        self.assertEqual(environment["EXPORT_S3_ENDPOINT"], "https://web-svc-seaweedfs")
        self.assertEqual(
            environment["EXPORT_S3_REGION"], SEAWEEDFS_SERVICES["seaweedfs"]["region"]
        )

    def test_the_export_environment_reuses_the_platform_values_of_the_workspaces_project(
        self,
    ):
        environment = export_environment()
        engine, stubs = templar()
        declared = engine.available_variables["SEMAPHORE_WORKSPACES_VARIABLES"]
        pairs = {
            "BAO_ADDR": "BAO_ADDR",
            "BAO_CACERT": "BAO_CACERT",
            "EXPORT_KEYCLOAK_URL": "KC_URL",
            "EXPORT_KEYCLOAK_REALM": "KC_REALM",
        }
        with stubbed(stubs):
            for export_name, workspaces_name in pairs.items():
                with self.subTest(name=export_name):
                    self.assertEqual(
                        environment[export_name],
                        engine.template(declared[workspaces_name]),
                    )
        self.assertEqual(environment["EXPORT_KEYCLOAK_URL"], "https://auth.example.org")
        self.assertEqual(environment["EXPORT_KEYCLOAK_REALM"], "main")

    def test_negative_control_a_dropped_variable_is_reported(self):
        self.assertEqual(
            environment_findings(export_environment(drop=("EXPORT_MAIL_FROM",))),
            ["EXPORT_MAIL_FROM is not set"],
        )

    def test_the_export_environment_reads_no_secret(self):
        declared = load_yaml_str(read_text(str(VARS)))
        self.assertEqual(secret_findings(declared["SEMAPHORE_EXPORT_VARIABLES"]), [])

    def test_negative_control_a_planted_secret_is_reported(self):
        declared = load_yaml_str(read_text(str(VARS)))
        planted = {
            **declared["SEMAPHORE_EXPORT_VARIABLES"],
            "KC_CLIENT_SECRET": "{{ SEMAPHORE_WORKSPACES_SECRETS.KC_CLIENT_SECRET }}",
        }
        self.assertEqual(secret_findings(planted), ["KC_CLIENT_SECRET reads a secret"])

    def test_the_mail_flags_follow_the_platform_mail_settings(self):
        for tls in (True, False):
            for auth in (True, False):
                with self.subTest(tls=tls, auth=auth):
                    environment = export_environment(
                        email={**EMAIL, "tls": tls, "auth": auth}
                    )
                    self.assertEqual(environment["EXPORT_MAIL_TLS"], str(tls).lower())
                    self.assertEqual(environment["EXPORT_MAIL_AUTH"], str(auth).lower())
                    self.assertNotIn(EMAIL["password"], json.dumps(environment))

    def test_the_relay_login_lands_where_export_py_reads_it(self):
        engine, stubs = templar()
        with stubbed(stubs):
            login = engine.template(
                engine.available_variables["SEMAPHORE_EXPORT_MAIL_LOGIN"]
            )
        self.assertEqual(
            (login["mount"], login["path"]),
            ("platform", load_task_module("export_task").MAIL_LOGIN_PATH),
        )
        self.assertEqual(
            login["data"],
            {"username": EMAIL["username"], "password": EMAIL["password"]},
        )
        task = mail_login_task()
        self.assertEqual(
            task["ansible.builtin.include_role"]["tasks_from"], "utils/kv.yml"
        )
        self.assertEqual(export_logins()["when"], "SEMAPHORE_WORKSPACES_ENABLED | bool")

    def test_the_s3_keys_land_where_export_py_reads_them(self):
        engine, _ = templar()
        login = engine.available_variables["SEMAPHORE_EXPORT_S3_LOGIN"]
        task = load_task_module("export_task")
        self.assertEqual(
            (login["mount"], login["path"]),
            (task.PLATFORM_MOUNT, task.S3_LOGIN_PATH),
        )
        self.assertEqual((login["mount"], login["path"]), ("platform", "export/s3"))
        self.assertEqual(sorted(login["data"]), ["access_key", "secret_key"])
        block = export_logins()
        (task,) = [
            t
            for t in block["block"]
            if "SEMAPHORE_EXPORT_S3_LOGIN" in str(t.get("vars"))
        ]
        self.assertEqual(
            task["ansible.builtin.include_role"],
            {"name": "web-app-openbao", "tasks_from": "utils/kv.yml"},
        )
        self.assertEqual(task["vars"]["openbao_kv_state"], "present")
        self.assertEqual(block["when"], "SEMAPHORE_WORKSPACES_ENABLED | bool")
        self.assertEqual(
            secret_findings(engine.available_variables["SEMAPHORE_EXPORT_VARIABLES"]),
            [],
        )


class TestOwnerAge(unittest.TestCase):
    def test_the_owner_age_lies_below_the_event_retention(self):
        self.assertEqual(DEFAULT_AGE, 7)
        self.assertEqual(owner_age_refusals(DEFAULT_AGE), [])
        self.assertEqual(owner_age_refusals(2), [])
        self.assertEqual(owner_age_refusals(RETENTION - 1), [])
        for age in (1, 0, RETENTION, RETENTION + 1, "7.5", "seven"):
            with self.subTest(age=age):
                self.assertNotEqual(owner_age_refusals(age), [])
        self.assertNotEqual(owner_age_refusals(DEFAULT_AGE, retention=DEFAULT_AGE), [])

    def test_the_assert_runs_on_every_deploy_with_workspaces(self):
        self.assertEqual(
            owner_age_task()["when"], "SEMAPHORE_WORKSPACES_ENABLED | bool"
        )
        self.assertNotIn("owner age of exports", read_text(str(CORE_TASKS)))
        self.assertIn("tasks_from: utils/stack/guard.yml", read_text(str(STACK_SERVE)))

    def test_negative_control_an_assert_without_the_retention_clause_passes_the_retention(
        self,
    ):
        clauses = owner_age_task()["ansible.builtin.assert"]["that"]
        dropped = [clause for clause in clauses if "RETENTION" not in clause]
        self.assertEqual(len(dropped), len(clauses) - 1)
        self.assertEqual(owner_age_refusals(RETENTION, that=dropped), [])

    def test_negative_control_an_assert_without_the_floor_passes_one_day(self):
        clauses = owner_age_task()["ansible.builtin.assert"]["that"]
        dropped = [clause for clause in clauses if ">= 2" not in clause]
        self.assertEqual(len(dropped), len(clauses) - 1)
        self.assertEqual(owner_age_refusals(1, that=dropped), [])


if __name__ == "__main__":
    unittest.main()
