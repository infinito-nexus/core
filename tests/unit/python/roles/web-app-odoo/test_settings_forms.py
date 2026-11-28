from __future__ import annotations

import json
import re
import unittest
from typing import TYPE_CHECKING

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLE = PROJECT_ROOT / "roles" / "web-app-odoo"
TASKS = ROLE / "tasks"
SQL = ROLE / "files" / "sql"
DRIFT = "tasks/utils/forms/drift.yml"
RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
PROVIDER_SQL = (
    SQL / "oidc" / "update" / "keycloak-provider.sql",
    SQL / "oidc" / "insert" / "keycloak-provider.sql",
)
NAMED_ARG = re.compile(r"%\((\w+)\)s")
JSON_KEY = re.compile(r"^\s*'(\w+)',", re.MULTILINE)
LDAP_SQL = (
    SQL / "update" / "res-company-ldap.sql",
    SQL / "insert-res-company-ldap.sql",
)
LDAP_READ = SQL / "select" / "res_company_ldap" / "fields.sql"
PROVIDER_READ = SQL / "oidc" / "select" / "keycloak" / "provider" / "fields.sql"
STORAGE_SQL = SQL / "objstore" / "upsert-fs-storage.sql"
STORAGE_READ = SQL / "objstore" / "select-fs-storage-fields.sql"
RECORDS = {
    "ldap_directory": ("ODOO_LDAP_SERVER", "services.odoo.directory.servers"),
    "attachment_storage": (
        "ODOO_OBJSTORE_STORAGE_CODE",
        "services.odoo.objstore.codes",
    ),
}


def _yaml(path: Path):
    return load_yaml_str(read_text(str(path)))


def _forms() -> dict:
    return _yaml(ROLE / ROLE_FILE_META_FORMS)


def _tasks(path: Path) -> list[dict]:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _render(expression, **variables):
    return Templar(loader=DataLoader(), variables=variables).template(expression)


def _task(path: Path, predicate) -> dict:
    return next(task for task in _tasks(path) if predicate(task))


def _upsert(path: Path, key: str) -> dict:
    def writes(task: dict) -> bool:
        named = task.get("database_query", {}).get("named_args")
        return isinstance(named, dict) and named.get("key") == key

    return _task(path, writes)


def _sql_args(path: Path) -> set[str]:
    return set(NAMED_ARG.findall(read_text(str(path))))


def _storage_application(managed: bool) -> dict:
    return {
        "services": {
            "odoo": {
                "directory": {
                    "managed": managed,
                    "servers": ["ldap.example"],
                    "port": 636,
                    "tls": True,
                    "base": "ou=users,dc=example",
                    "filter": "(uid=%s)",
                    "create_user": True,
                },
                "objstore": {
                    "managed": managed,
                    "codes": ["seaweedfs"],
                    "name": "Infinito Object Store",
                    "bucket": "odoo",
                    "cacheable": True,
                    "default_for_attachments": True,
                    "base_url": "",
                    "directory_path_in_url": False,
                },
            },
        },
    }


def _application(registration: bool, native: bool, sso: bool = True) -> dict:
    return {
        "services": {
            "sso": {"enabled": sso},
            "odoo": {
                "login": {
                    "method": {
                        "registration": {"enabled": registration},
                        "native": {"enabled": native},
                        "sso": {"enabled": sso},
                    }
                },
                "base_url": {
                    "parameters": ["web.base.url"],
                    "value": "https://odoo.example",
                },
                "base_url_freeze": {
                    "parameters": ["web.base.url.freeze"],
                    "value": "True",
                },
                "oauth": {
                    "providers": ["Keycloak"],
                    "client_id": "odoo",
                    "body": "Login with SSO",
                    "css_class": "fa fa-fw fa-key",
                    "auth_endpoint": "https://sso.example/auth",
                    "scope": "openid email profile phone",
                    "validation_endpoint": "https://sso.example/userinfo",
                    "data_endpoint": "https://sso.example/userinfo",
                },
            },
        },
    }


class TestTheFormsMapTheLoginMethods(unittest.TestCase):
    def test_the_general_form_stores_what_the_role_wrote_before(self) -> None:
        for registration, native in ((True, True), (False, False), (True, False)):
            with self.subTest(registration=registration, native=native):
                self.assertEqual(
                    {
                        "auth_signup_uninvited": "b2c" if registration else "b2b",
                        "auth_signup_reset_password": "True" if native else "False",
                    },
                    values("general", _forms(), _application(registration, native), {}),
                )

    def test_the_sso_forms_apply_only_with_sso(self) -> None:
        for form in ("base_url", "base_url_freeze", "oauth_provider"):
            with self.subTest(form=form):
                self.assertNotEqual(
                    {}, values(form, _forms(), _application(True, True), {})
                )
                self.assertEqual(
                    {}, values(form, _forms(), _application(True, True, False), {})
                )

    def test_the_provider_form_holds_exactly_the_columns_the_role_writes(self) -> None:
        fields = set(_forms()["oauth_provider"]["fields"])
        for path in PROVIDER_SQL:
            with self.subTest(sql=path.name):
                self.assertEqual(fields, _sql_args(path))
        read = read_text(str(PROVIDER_READ))
        self.assertEqual(fields, set(JSON_KEY.findall(read)))

    def test_the_record_names_the_provider_the_role_writes(self) -> None:
        providers = _yaml(ROLE / ROLE_FILE_META_SERVICES)["odoo"]["oauth"]["providers"]
        self.assertEqual(
            "services.odoo.oauth.providers",
            _forms()["oauth_provider"]["record"]["source"],
        )
        for path in (*PROVIDER_SQL, PROVIDER_READ):
            with self.subTest(sql=path.name):
                self.assertEqual(
                    providers,
                    re.findall(r"'(Keycloak)'", read_text(str(path))),
                )

    def test_the_settings_read_returns_exactly_the_declared_fields(self) -> None:
        read = read_text(str(SQL / "select" / "managed-settings.sql"))
        declared = {
            key
            for form in ("general", "base_url", "base_url_freeze")
            for key in [form, *_forms()[form]["fields"]]
        }
        self.assertEqual(declared, set(JSON_KEY.findall(read)))


class TestTheDirectoryAndStorageForms(unittest.TestCase):
    def test_they_apply_only_while_the_role_manages_them(self) -> None:
        for form, expected in (
            (
                "ldap_directory",
                {
                    "ldap_server_port": 636,
                    "ldap_tls": True,
                    "ldap_base": "ou=users,dc=example",
                    "ldap_filter": "(uid=%s)",
                    "create_user": True,
                },
            ),
            (
                "attachment_storage",
                {
                    "storage_name": "Infinito Object Store",
                    "directory_path": "odoo",
                    "is_cacheable": True,
                    "use_as_default_for_attachments": True,
                    "storage_base_url": "",
                    "is_directory_path_in_url": False,
                },
            ),
        ):
            with self.subTest(form=form):
                self.assertEqual(
                    expected, values(form, _forms(), _storage_application(True), {})
                )
                self.assertEqual(
                    {}, values(form, _forms(), _storage_application(False), {})
                )

    def test_the_reads_return_exactly_the_declared_fields(self) -> None:
        for form, read in (
            ("ldap_directory", LDAP_READ),
            ("attachment_storage", STORAGE_READ),
        ):
            with self.subTest(form=form):
                self.assertEqual(
                    set(_forms()[form]["fields"]),
                    set(JSON_KEY.findall(read_text(str(read)))),
                )

    def test_the_writes_take_every_declared_field_and_no_secret(self) -> None:
        vars_main = _yaml(ROLE / ROLE_FILE_VARS_MAIN)
        config = set(vars_main["ODOO_LDAP_CONFIG"])
        fields = set(_forms()["ldap_directory"]["fields"])
        self.assertEqual(set(), fields & config)
        for path in LDAP_SQL:
            with self.subTest(sql=path.name):
                self.assertLessEqual(fields, _sql_args(path))
                self.assertLessEqual(_sql_args(path), fields | config)
        storage = set(_forms()["attachment_storage"]["fields"])
        self.assertEqual(
            storage | {"code", "options", "force_db_rules"}, _sql_args(STORAGE_SQL)
        )
        for form in ("ldap_directory", "attachment_storage"):
            for field in _forms()[form]["fields"]:
                with self.subTest(form=form, field=field):
                    self.assertNotRegex(field, "password|secret|key|bind")

    def test_the_records_name_the_rows_the_role_writes(self) -> None:
        vars_main = _yaml(ROLE / ROLE_FILE_VARS_MAIN)
        for form, (var, source) in RECORDS.items():
            with self.subTest(form=form):
                self.assertEqual(source, _forms()[form]["record"]["source"])
                self.assertEqual(
                    f"{{{{ lookup('config', application_id, '{source}') | first }}}}",
                    vars_main[var],
                )


class TestTheConvergeWritesTheSinks(unittest.TestCase):
    def test_the_signup_settings_come_from_the_general_sink(self) -> None:
        tasks = TASKS / "08_login_methods.yml"
        sink = {"auth_signup_uninvited": "b2c", "auth_signup_reset_password": "False"}
        for key, field in (
            ("auth_signup.invitation_scope", "auth_signup_uninvited"),
            ("auth_signup.reset_password", "auth_signup_reset_password"),
        ):
            with self.subTest(key=key):
                expression = _upsert(tasks, key)["database_query"]["named_args"]
                self.assertEqual(
                    sink[field],
                    _render(expression["value"], ODOO_SIGNUP_SETTINGS=sink),
                )
        website = _task(
            tasks,
            lambda task: (
                "website-signup-scope.sql"
                in str(task.get("database_query", {}).get("query_file", ""))
            ),
        )
        self.assertEqual(
            "b2c",
            _render(
                website["database_query"]["named_args"]["scope"],
                ODOO_SIGNUP_SETTINGS=sink,
            ),
        )

    def test_the_base_url_comes_from_its_sink(self) -> None:
        sink = {"web_base_url": "https://odoo.example", "web_base_url_freeze": "True"}
        for key, field in (
            ("web.base.url", "web_base_url"),
            ("web.base.url.freeze", "web_base_url_freeze"),
        ):
            with self.subTest(key=key):
                expression = _upsert(TASKS / "05_oidc.yml", key)["database_query"]
                self.assertEqual(
                    sink[field],
                    _render(expression["named_args"]["value"], ODOO_BASE_URL=sink),
                )

    def test_the_provider_is_written_from_its_sink(self) -> None:
        sink = values("oauth_provider", _forms(), _application(True, True), {})
        for sql in ("update/keycloak-provider.sql", "insert/keycloak-provider.sql"):
            with self.subTest(sql=sql):
                task = _task(
                    TASKS / "05_oidc.yml",
                    lambda task, sql=sql: str(
                        task.get("database_query", {}).get("query_file", "")
                    ).endswith(sql),
                )
                self.assertEqual(
                    sink,
                    _render(
                        task["database_query"]["named_args"], ODOO_OAUTH_PROVIDER=sink
                    ),
                )

    def test_the_ldap_server_is_written_from_its_sink(self) -> None:
        sink = values("ldap_directory", _forms(), _storage_application(True), {})
        config = {"ldap_server": "ldap.example", "ldap_binddn": "cn=admin"}
        for sql in ("update/res-company-ldap.sql", "insert-res-company-ldap.sql"):
            with self.subTest(sql=sql):
                task = _task(
                    TASKS / "06_ldap.yml",
                    lambda task, sql=sql: str(
                        task.get("database_query", {}).get("query_file", "")
                    ).endswith(sql),
                )
                self.assertEqual(
                    {**sink, **config},
                    _render(
                        task["database_query"]["named_args"],
                        ODOO_LDAP_DIRECTORY=sink,
                        ODOO_LDAP_CONFIG=config,
                    ),
                )

    def test_the_attachment_storage_is_written_from_its_sink(self) -> None:
        sink = values("attachment_storage", _forms(), _storage_application(True), {})
        task = _task(
            TASKS / "07_objstore.yml",
            lambda task: str(
                task.get("database_query", {}).get("query_file", "")
            ).endswith("upsert-fs-storage.sql"),
        )
        rendered = _render(
            task["database_query"]["named_args"],
            ODOO_OBJSTORE_SETTINGS=sink,
            ODOO_OBJSTORE_STORAGE_CODE="seaweedfs",
            ODOO_OBJSTORE_OPTIONS={"key": "k"},
            ODOO_OBJSTORE_FORCE_DB_RULES="{}",
        )
        self.assertEqual(sink, {key: rendered[key] for key in sink})
        self.assertEqual("seaweedfs", rendered["code"])


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_report_runs_before_every_write(self) -> None:
        steps = [
            task.get("include_tasks") for task in _yaml(TASKS / "01_manager_ops.yml")
        ]
        report = steps.index("utils/settings_drift.yml")
        self.assertLess(report, steps.index("05_oidc.yml"))
        self.assertLess(report, steps.index("06_ldap.yml"))
        self.assertLess(report, steps.index("08_login_methods.yml"))

    def test_the_ldap_write_and_its_read_share_one_condition(self) -> None:
        steps = _yaml(TASKS / "01_manager_ops.yml")
        write = next(
            step for step in steps if step.get("include_tasks") == "06_ldap.yml"
        )
        read = _task(
            TASKS / "utils" / "settings_drift.yml",
            lambda task: (
                "res_company_ldap/fields.sql"
                in str(task.get("database_query", {}).get("query_file", ""))
            ),
        )
        self.assertEqual("ODOO_LDAP_MANAGED | bool", write["when"])
        self.assertEqual("ODOO_LDAP_MANAGED | bool", read["when"])

    def test_the_storage_report_runs_before_the_storage_writes(self) -> None:
        tasks = _tasks(TASKS / "07_objstore.yml")
        report = next(
            index
            for index, task in enumerate(tasks)
            if DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
        )
        reads = [
            index
            for index, task in enumerate(tasks)
            if task.get("register") == "odoo_attachment_storage_stored"
        ]
        writes = [
            index
            for index, task in enumerate(tasks)
            if "mask_values" in task.get("database_query", {})
        ]
        self.assertEqual(1, len(reads))
        self.assertEqual(2, len(writes))
        self.assertLess(reads[0], report)
        self.assertLess(report, min(writes))
        self.assertEqual(
            {"attachment_storage": {"storage_name": "x"}},
            _render(
                tasks[report]["vars"]["forms_drift_current"],
                odoo_attachment_storage_stored={"rows": [['{"storage_name": "x"}']]},
            ),
        )

    def test_the_report_reads_what_the_store_returned(self) -> None:
        tasks = _tasks(TASKS / "utils" / "settings_drift.yml")
        report = next(
            task
            for task in tasks
            if DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
        )
        self.assertLess(
            max(index for index, task in enumerate(tasks) if "database_query" in task),
            tasks.index(report),
        )
        stored = {
            "general": {"auth_signup_uninvited": "b2b"},
            "base_url": {},
            "base_url_freeze": {},
        }
        for provider, expected in (
            ({"rows": [['{"client_id": "odoo"}']]}, {"client_id": "odoo"}),
            ({"skipped": True}, {}),
        ):
            with self.subTest(provider=provider):
                self.assertEqual(
                    {
                        **stored,
                        "oauth_provider": expected,
                        "ldap_directory": {"ldap_base": "dc=x"},
                    },
                    _render(
                        report["vars"]["forms_drift_current"],
                        odoo_managed_settings_stored={"rows": [[json.dumps(stored)]]},
                        odoo_oauth_provider_stored=provider,
                        odoo_ldap_directory_stored={
                            "rows": [['{"ldap_base": "dc=x"}']]
                        },
                        ODOO_LDAP_MANAGED=True,
                    ),
                )
        self.assertEqual(
            {},
            _render(
                report["vars"]["forms_drift_current"],
                odoo_managed_settings_stored={"rows": [[json.dumps(stored)]]},
                odoo_oauth_provider_stored={"skipped": True},
                odoo_ldap_directory_stored={"skipped": True},
                ODOO_LDAP_MANAGED=False,
            )["ldap_directory"],
        )


class TestTheRendererLocksTheForms(unittest.TestCase):
    def test_the_role_loads_the_shared_renderer_on_every_page(self) -> None:
        self.assertIn(
            RENDERER,
            read_text(str(ROLE / "templates" / "javascript.js.j2")),
        )
        self.assertIs(
            True, _yaml(ROLE / ROLE_FILE_META_SERVICES)["javascript"]["enabled"]
        )


if __name__ == "__main__":
    unittest.main()
