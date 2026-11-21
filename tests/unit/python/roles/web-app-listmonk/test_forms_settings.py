from __future__ import annotations

import json
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-listmonk"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
TASKS = ROLE / "tasks" / "02_manager_ops.yml"
APPLY = ROLE / "templates" / "sql" / "apply_settings.sql.j2"
DESIGN = ROLE / "templates" / "design" / "appearance.sql.j2"
READ = ROLE / "files" / "sql" / "select" / "managed_settings.sql"
LOADER = ROLE / "templates" / "javascript.js.j2"
SHARED_RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
DRIFT = "tasks/utils/forms/drift.yml"
OIDC_SINK = "LISTMONK_OIDC_SETTINGS"
CAPTCHA_SINK = "LISTMONK_CAPTCHA_SETTINGS"
OBJECT_FORMS = {"security", "captcha"}
PREFIXED = "LISTMONK_PREFIXED_FORMS"
SINKS = {
    "general": "LISTMONK_GENERAL_SETTINGS",
    "upload": "LISTMONK_UPLOAD_SETTINGS",
    "s3": "LISTMONK_S3_SETTINGS",
    "bounce": "LISTMONK_BOUNCE_SETTINGS",
}
PREFIXES = {
    "general": "app.",
    "upload": "upload.",
    "s3": "upload.s3.",
    "bounce": "bounce.",
}
SECRETS = ("aws_access_key_id", "aws_secret_access_key")
CAPTCHA_SECRETS = ("key", "secret")
CAPTCHA_CREDENTIAL = (
    "lookup('config', application_id, 'secrets.credentials.hcaptcha.{credential}')"
)
LEGACY_CAPTCHA_KEYS = (
    "security.enable_captcha",
    "security.captcha_key",
    "security.captcha_secret",
)
APPLIED = re.compile(r"\$infinito_settings\$(.*)\$infinito_settings\$", re.DOTALL)


def _vars() -> dict:
    return load_yaml_any(str(VARS))


def _forms() -> dict:
    return load_yaml_any(str(FORMS))


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _render(template: str, variables: dict):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _reads(task: dict) -> bool:
    return "managed_settings.sql" in str(task.get("ansible.builtin.shell", {}))


def _reports(task: dict) -> bool:
    return DRIFT in str(task.get("ansible.builtin.include_tasks", ""))


def _applies(task: dict) -> bool:
    return "apply_settings.sql.j2" in str(task.get("ansible.builtin.shell", {}))


def _prefixed(sinks: dict) -> dict:
    return {
        form: {"prefix": PREFIXES[form], "fields": fields}
        for form, fields in sinks.items()
    }


def _application(s3: bool) -> dict:
    services = load_yaml_any(str(SERVICES))
    listmonk = services["listmonk"]
    return {
        "forms": _forms(),
        "services": {
            "sso": {"enabled": False},
            "listmonk": {
                "settings": {
                    **listmonk["settings"],
                    "root_url": "https://lists.example",
                    "from_email": "news@example.org",
                    "lang": "de",
                    "site_name": "Lists",
                    "logo_url": "https://cdn.example/logo.svg",
                    "favicon_url": "https://cdn.example/favicon.ico",
                },
                "upload": {
                    "provider": listmonk["upload"]["provider"],
                    "s3": {
                        "enabled": s3,
                        "aws_default_region": "eu-1",
                        "bucket": "listmonk",
                        "bucket_type": listmonk["upload"]["s3"]["bucket_type"],
                        "url": "https://s3.example",
                        "public_url": "https://files.example/listmonk",
                    },
                },
                "bounce": listmonk["bounce"],
            },
        },
    }


class TestTheFormsFile(unittest.TestCase):
    def test_each_prefixed_field_is_the_setting_its_selector_names(self) -> None:
        forms = _forms()
        for form, prefix in PREFIXES.items():
            self.assertEqual([SINKS[form]], forms[form]["sinks"])
            for field, spec in forms[form]["fields"].items():
                with self.subTest(form=form, field=field):
                    self.assertIn(f'[name="{prefix}{field}"]', spec["selector"])

    def test_the_oidc_fields_apply_with_sso_and_leave_the_secret_out(self) -> None:
        security = _forms()["security"]
        self.assertEqual([OIDC_SINK], security["sinks"])
        self.assertNotIn("client_secret", security["fields"])
        for field, spec in security["fields"].items():
            with self.subTest(field=field):
                self.assertEqual("services.sso.enabled", spec["when"])

    def test_the_media_fields_apply_with_the_object_store_and_hold_no_secret(
        self,
    ) -> None:
        forms = _forms()
        for form in ("upload", "s3"):
            for field, spec in forms[form]["fields"].items():
                with self.subTest(form=form, field=field):
                    self.assertEqual(
                        "services.listmonk.upload.s3.enabled", spec["when"]
                    )
                    self.assertNotIn(field, SECRETS)

    def test_the_captcha_form_follows_hcaptcha_and_leaves_its_credentials_out(
        self,
    ) -> None:
        captcha = _forms()["captcha"]
        self.assertEqual([CAPTCHA_SINK], captcha["sinks"])
        self.assertEqual({"enabled"}, set(captcha["fields"]))
        spec = captcha["fields"]["enabled"]
        self.assertEqual("services.hcaptcha.enabled", spec["when"])
        self.assertEqual('input[name="security.captcha"]', spec["selector"])
        for secret in CAPTCHA_SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, captcha["fields"])


class TestTheSinksCarryTheSources(unittest.TestCase):
    def test_the_captcha_form_applies_only_with_hcaptcha(self) -> None:
        for enabled in (True, False):
            application = {
                "forms": _forms(),
                "services": {"hcaptcha": {"enabled": enabled}},
            }
            with self.subTest(enabled=enabled):
                self.assertEqual(
                    {"enabled": True} if enabled else {},
                    values("captcha", _forms(), application, {}),
                )

    def test_the_object_store_switches_the_media_forms(self) -> None:
        for s3 in (True, False):
            application = _application(s3)
            with self.subTest(s3=s3):
                self.assertEqual(
                    {"provider": "s3"} if s3 else {},
                    values("upload", _forms(), application, {}),
                )
                self.assertEqual(
                    {
                        "aws_default_region": "eu-1",
                        "bucket": "listmonk",
                        "bucket_type": "public",
                        "url": "https://s3.example",
                        "public_url": "https://files.example/listmonk",
                    }
                    if s3
                    else {},
                    values("s3", _forms(), application, {}),
                )

    def test_bounce_processing_stays_on_and_the_branding_is_general(self) -> None:
        application = _application(False)
        self.assertEqual({"enabled": True}, values("bounce", _forms(), application, {}))
        general = values("general", _forms(), application, {})
        self.assertEqual("Lists", general["site_name"])
        self.assertEqual("https://cdn.example/logo.svg", general["logo_url"])
        self.assertEqual("https://cdn.example/favicon.ico", general["favicon_url"])

    def test_the_design_sources_fall_back_when_the_design_is_off(self) -> None:
        settings = load_yaml_any(str(SERVICES))["listmonk"]["settings"]
        for field, design, fallback in (
            ("site_name", ".label", "service_provider.company.titel"),
            ("logo_url", ".urls.header.svg", "service_provider.platform.logo"),
            ("favicon_url", ".urls.favicon_ico", "service_provider.platform.favicon"),
        ):
            with self.subTest(field=field):
                self.assertIn(
                    f"lookup('design', 'web-app-listmonk'){design} if lookup("
                    "'config', 'web-app-listmonk', 'services.design.enabled') | bool"
                    f" else {fallback}",
                    settings[field],
                )


class TestTheWriteReadsTheSinks(unittest.TestCase):
    def test_the_sinks_read_only_their_forms(self) -> None:
        variables = _vars()
        for form, sink in (
            *SINKS.items(),
            ("security", OIDC_SINK),
            ("captcha", CAPTCHA_SINK),
        ):
            with self.subTest(sink=sink):
                self.assertEqual(
                    f"{{{{ lookup('form_values', application_id, '{form}') }}}}",
                    variables[sink],
                )

    def test_every_prefixed_form_carries_its_sink_under_its_prefix(self) -> None:
        self.assertEqual(
            {
                form: {"prefix": PREFIXES[form], "fields": f"{{{{ {sink} }}}}"}
                for form, sink in SINKS.items()
            },
            _vars()[PREFIXED],
        )
        self.assertEqual(set(_forms()) - OBJECT_FORMS, set(_vars()[PREFIXED]))

    def test_no_managed_field_is_written_outside_its_sink(self) -> None:
        variables = _vars()
        forms = _forms()
        managed = {
            PREFIXES[form] + field
            for form in PREFIXES
            for field in forms[form]["fields"]
        }
        written = {
            setting["key"]
            for entries in variables.values()
            if isinstance(entries, list)
            for setting in entries
            if isinstance(setting, dict) and "key" in setting
        }
        self.assertEqual(set(), managed & written)
        self.assertNotIn("BRANDING", read_text(str(DESIGN)))

    def test_the_object_store_secrets_stay_out_of_the_sinks(self) -> None:
        settings = {setting["key"]: setting for setting in _vars()["LISTMONK_SETTINGS"]}
        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertIn("condition", settings[f"upload.s3.{secret}"])

    def test_the_apply_writes_each_field_under_its_setting(self) -> None:
        rendered = _render(
            read_text(str(APPLY)),
            {
                "LISTMONK_SETTINGS": [{"key": "smtp", "value": "[]"}],
                PREFIXED: _prefixed(
                    {
                        "general": {"root_url": "https://lists.example"},
                        "upload": {"provider": "s3"},
                        "s3": {"bucket": "listmonk"},
                        "bounce": {"enabled": True},
                    }
                ),
            },
        )
        self.assertEqual(
            {
                "smtp": [],
                "app.root_url": "https://lists.example",
                "upload.provider": "s3",
                "upload.s3.bucket": "listmonk",
                "bounce.enabled": True,
            },
            json.loads(APPLIED.search(rendered).group(1)),
        )

    def test_the_oidc_setting_is_the_sink_plus_the_client_secret(self) -> None:
        entry = next(
            setting
            for setting in _vars()["LISTMONK_SETTINGS"]
            if setting["key"] == "security.oidc"
        )
        sink = {
            "enabled": True,
            "provider_url": "https://sso.example/realms/main",
            "client_id": "listmonk",
            "auto_create_users": False,
        }
        rendered = _render(
            entry["value"],
            {OIDC_SINK: sink, "OIDC": {"CLIENT": {"SECRET": "probe-secret"}}},
        )
        self.assertEqual(
            {**sink, "client_secret": "probe-secret"}, json.loads(rendered)
        )

    def test_the_captcha_is_written_as_the_one_v6_object(self) -> None:
        settings = {setting["key"]: setting for setting in _vars()["LISTMONK_SETTINGS"]}
        for legacy in LEGACY_CAPTCHA_KEYS:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, settings)
        entry = settings["security.captcha"]
        value = entry["value"]
        for credential in CAPTCHA_SECRETS:
            lookup = CAPTCHA_CREDENTIAL.format(credential=credential)
            self.assertEqual(1, value.count(lookup))
            value = value.replace(lookup, f"probe_{credential}")
        variables = {
            CAPTCHA_SINK: {"enabled": True},
            "probe_key": "probe-key",
            "probe_secret": "probe-secret",
        }
        self.assertEqual(
            {
                "altcha": {"enabled": False, "complexity": 300000},
                "hcaptcha": {
                    "enabled": True,
                    "key": "probe-key",
                    "secret": "probe-secret",
                },
            },
            json.loads(_render(value, variables)),
        )
        for sink, written in (({"enabled": True}, True), ({}, False)):
            with self.subTest(sink=sink):
                self.assertIs(
                    written,
                    _render(entry["condition"], {CAPTCHA_SINK: sink}),
                )


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_store_is_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks()
        self.assertLess(_index(tasks, _reads), _index(tasks, _reports))
        self.assertLess(_index(tasks, _reports), _index(tasks, _applies))

    def test_the_read_asks_for_every_prefixed_form(self) -> None:
        read = next(task for task in _tasks() if _reads(task))
        forms = _prefixed({"general": {"lang": "de"}, "s3": {}})
        command = _render(
            read["ansible.builtin.shell"]["cmd"],
            {"LISTMONK_EXEC_DATABASE": "psql", PREFIXED: forms},
        )
        self.assertIn(f"-v forms='{json.dumps(forms)}'", command)

    def test_the_read_never_returns_the_client_secret(self) -> None:
        sql = read_text(str(READ))
        self.assertIn("jsonb_each(:'forms'::jsonb) AS form", sql)
        self.assertIn("jsonb_object_keys(form.value -> 'fields')", sql)
        self.assertIn("(form.value ->> 'prefix') || field", sql)
        self.assertIn("value - 'client_secret'", sql)

    def test_the_read_returns_only_the_hcaptcha_switch(self) -> None:
        sql = read_text(str(READ))
        self.assertIn("WHERE key = 'security.captcha'", sql)
        self.assertIn(
            "jsonb_build_object('enabled', value -> 'hcaptcha' -> 'enabled')", sql
        )
        for credential in CAPTCHA_SECRETS:
            with self.subTest(credential=credential):
                self.assertNotRegex(sql, rf"->>? '{credential}'")

    def test_the_report_reads_what_the_store_returned(self) -> None:
        report = next(task for task in _tasks() if _reports(task))
        stored = {"general": {"lang": "en"}, "s3": {}, "security": {"enabled": True}}
        self.assertEqual(
            stored,
            _render(
                report["vars"]["forms_drift_current"],
                {"listmonk_settings_stored": {"stdout": json.dumps(stored)}},
            ),
        )


class TestTheSettingsPageIsLocked(unittest.TestCase):
    def test_the_loader_includes_the_shared_renderer(self) -> None:
        self.assertIn(SHARED_RENDERER, read_text(str(LOADER)))

    def test_the_javascript_service_is_literally_on(self) -> None:
        services = load_yaml_any(str(SERVICES))
        self.assertIs(True, services["javascript"]["enabled"])


if __name__ == "__main__":
    unittest.main()
