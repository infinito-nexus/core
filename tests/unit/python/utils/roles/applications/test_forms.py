from __future__ import annotations

import copy
import tempfile
import textwrap
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache import applications as cache_apps
from utils.cache.reset import _reset_cache_for_tests
from utils.roles.applications import drift, form_schema, forms
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SERVICES

FORMS = {
    "general": {
        "path": "/wp-admin/options-general.php",
        "fields": {
            "admin_email": {
                "source": "users.platform_administrator.email",
                "mode": "seeded",
                "selector": "#new_admin_email",
            },
            "blogname": {
                "source": "design.label",
                "mode": "enforced",
                "selector": "#blogname",
                "label": "Site Title",
                "type": "text",
            },
        },
    },
    "smtp": {
        "path": "/settings/admin",
        "fields": {
            "password": {
                "source": "secrets.credentials.smtp.password",
                "mode": "enforced",
                "selector": "#mail_smtppassword",
                "type": "password",
            },
        },
    },
}

APPLICATION = {"design": {"label": "Infinito.Nexus"}, "secrets": {"credentials": {}}}
USERS = {"platform_administrator": {"email": "admin@example.com", "password": "pw"}}
CREDENTIALS = {"smtp": {"password": {"algorithm": "alphanumeric", "length": 32}}}
SYNTH = "SYNTH-SECRET-1"
JWT_SHAPED = f"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ{SYNTH}.{SYNTH}-sig"
SENDGRID_SHAPED = f"SG.{SYNTH}.abcdefABCDEF0123456789"
ISSUE = "https://example.invalid/upstream/issues/1"


def _field(form: str, field: str) -> dict:
    return copy.deepcopy(FORMS)[form]["fields"][field]


def _with_field(form: str, field: str, spec: dict) -> dict:
    data = copy.deepcopy(FORMS)
    data[form]["fields"][field] = spec
    return data


class TestSchema(unittest.TestCase):
    def test_a_well_formed_file_passes(self):
        self.assertEqual([], form_schema.schema_errors("web-app-x", FORMS))

    def test_each_required_key_is_enforced(self):
        for key in form_schema.REQUIRED_FIELD_KEYS:
            with self.subTest(key=key):
                spec = _field("general", "blogname")
                del spec[key]
                errors = form_schema.schema_errors(
                    "web-app-x", _with_field("general", "blogname", spec)
                )
                self.assertEqual(
                    [f"web-app-x: general.fields.blogname lacks `{key}`"], errors
                )

    def test_an_unknown_mode_is_refused(self):
        spec = {**_field("general", "blogname"), "mode": "locked"}
        errors = form_schema.schema_errors(
            "web-app-x", _with_field("general", "blogname", spec)
        )
        self.assertEqual(1, len(errors))
        self.assertIn("mode 'locked' is not one of", errors[0])

    def test_an_unknown_field_key_is_refused(self):
        spec = {**_field("general", "blogname"), "secret": True}
        errors = form_schema.schema_errors(
            "web-app-x", _with_field("general", "blogname", spec)
        )
        self.assertEqual(1, len(errors))
        self.assertIn("secret is not a known key", errors[0])

    def test_a_source_must_be_a_dotted_path(self):
        spec = {**_field("general", "blogname"), "source": "{{ design.label }}"}
        errors = form_schema.schema_errors(
            "web-app-x", _with_field("general", "blogname", spec)
        )
        self.assertEqual(
            [
                (
                    "web-app-x: general.fields.blogname.source must hold no template;"
                    f" {ROLE_FILE_META_FORMS} is never rendered"
                ),
                "web-app-x: general.fields.blogname.source must be a dotted inventory path",
            ],
            errors,
        )

    def test_an_empty_selector_is_refused(self):
        spec = {**_field("general", "blogname"), "selector": " "}
        errors = form_schema.schema_errors(
            "web-app-x", _with_field("general", "blogname", spec)
        )
        self.assertEqual(
            ["web-app-x: general.fields.blogname.selector must be a non-empty string"],
            errors,
        )

    def test_a_form_needs_an_absolute_page_path(self):
        data = copy.deepcopy(FORMS)
        data["general"]["path"] = "wp-admin/options-general.php"
        self.assertEqual(
            ["web-app-x: general.path must be the admin page path, starting with /"],
            form_schema.schema_errors("web-app-x", data),
        )

    def test_a_form_without_fields_is_refused(self):
        data = copy.deepcopy(FORMS)
        data["general"]["fields"] = {}
        self.assertEqual(
            ["web-app-x: general.fields must map each field to its spec"],
            form_schema.schema_errors("web-app-x", data),
        )

    def test_an_unknown_type_and_a_broken_validation_are_refused(self):
        spec = {
            **_field("general", "blogname"),
            "type": "slider",
            "validation": "([a-z]",
        }
        errors = form_schema.schema_errors(
            "web-app-x", _with_field("general", "blogname", spec)
        )
        self.assertEqual(2, len(errors))
        self.assertIn("type 'slider' is not one of", errors[0])
        self.assertIn("validation is no regular expression", errors[1])

    def test_a_file_upload_field_passes(self):
        spec = {**_field("general", "blogname"), "type": "file"}
        self.assertEqual(
            [],
            form_schema.schema_errors(
                "web-app-x", _with_field("general", "blogname", spec)
            ),
        )

    def test_an_optional_field_passes(self):
        spec = {**_field("general", "blogname"), "optional": True}
        self.assertEqual(
            [],
            form_schema.schema_errors(
                "web-app-x", _with_field("general", "blogname", spec)
            ),
        )

    def test_optional_must_be_true(self):
        for value in (False, "true", 1):
            with self.subTest(value=value):
                spec = {**_field("general", "blogname"), "optional": value}
                errors = form_schema.schema_errors(
                    "web-app-x", _with_field("general", "blogname", spec)
                )
                self.assertEqual(1, len(errors))
                self.assertIn("blogname.optional must be true", errors[0])

    def test_an_sso_field_takes_no_optional(self):
        spec = {"source": "sso.EMAIL", "mode": "enforced", "selector": "#email"}
        errors = form_schema.schema_errors(
            "web-app-x",
            _with_field("general", "email", {**spec, "optional": True}),
        )
        self.assertEqual(1, len(errors))
        self.assertIn("email.optional takes no sso.<ATTRIBUTE> source", errors[0])

    def test_an_env_name_passes(self):
        spec = {**_field("general", "blogname"), "env": "FTLCONF_webserver_domain"}
        self.assertEqual(
            [],
            form_schema.schema_errors(
                "web-app-x", _with_field("general", "blogname", spec)
            ),
        )

    def test_an_env_that_names_no_variable_is_refused(self):
        for env in ("FTL-X", "1FTL", "", "FTL X", 5):
            with self.subTest(env=env):
                spec = {**_field("general", "blogname"), "env": env}
                self.assertEqual(
                    [
                        (
                            "web-app-x: general.fields.blogname.env must be an"
                            " environment variable name"
                        )
                    ],
                    form_schema.schema_errors(
                        "web-app-x", _with_field("general", "blogname", spec)
                    ),
                )

    def test_two_fields_naming_one_variable_are_refused(self):
        data = copy.deepcopy(FORMS)
        for field in ("admin_email", "blogname"):
            data["general"]["fields"][field]["env"] = "SITE"
        self.assertEqual(
            ["web-app-x: general.fields: two fields name the variable SITE"],
            form_schema.schema_errors("web-app-x", data),
        )

    def test_a_template_in_any_forms_string_is_refused(self):
        for key, value in (
            ("label", "{{ site_title }}"),
            ("description", "Managed {% if x %}here{% endif %}"),
            ("selector", "#{{ id }}"),
            ("enum", ["a", "{{ b }}"]),
            ("validation", "^{{ pattern }}$"),
        ):
            with self.subTest(key=key):
                spec = {**_field("general", "blogname"), key: value}
                self.assertIn(
                    f"web-app-x: general.fields.blogname.{key} must hold no template;"
                    f" {ROLE_FILE_META_FORMS} is never rendered",
                    form_schema.schema_errors(
                        "web-app-x", _with_field("general", "blogname", spec)
                    ),
                )
        data = copy.deepcopy(FORMS)
        data["general"]["path"] = "/{{ admin_path }}"
        self.assertIn(
            f"web-app-x: general.path must hold no template; {ROLE_FILE_META_FORMS} is never rendered",
            form_schema.schema_errors("web-app-x", data),
        )

    def test_an_empty_file_is_refused(self):
        self.assertEqual(1, len(form_schema.schema_errors("web-app-x", {})))
        self.assertEqual(1, len(form_schema.schema_errors("web-app-x", None)))

    def test_a_scalar_map_and_a_negated_when_pass(self):
        spec = {
            **_field("general", "blogname"),
            "when": "!design.enabled",
            "map": {True: "1", False: "0", "open": 2},
        }
        self.assertEqual(
            [],
            form_schema.schema_errors(
                "web-app-x", _with_field("general", "blogname", spec)
            ),
        )

    def test_a_map_that_maps_nothing_or_to_a_structure_is_refused(self):
        for table in ({}, [True, "1"], {True: ["1"]}, {True: None}):
            with self.subTest(table=table):
                spec = {**_field("general", "blogname"), "map": table}
                self.assertEqual(
                    [
                        (
                            "web-app-x: general.fields.blogname.map must map each "
                            "source value to a scalar the app stores"
                        )
                    ],
                    form_schema.schema_errors(
                        "web-app-x", _with_field("general", "blogname", spec)
                    ),
                )

    def test_a_negation_needs_a_dotted_path(self):
        for when in ("!", "!!design.enabled", "!design"):
            with self.subTest(when=when):
                spec = {**_field("general", "blogname"), "when": when}
                self.assertEqual(
                    [
                        (
                            "web-app-x: general.fields.blogname.when must be a dotted "
                            "inventory path"
                        )
                    ],
                    form_schema.schema_errors(
                        "web-app-x", _with_field("general", "blogname", spec)
                    ),
                )

    def test_a_form_naming_its_sinks_passes(self):
        data = copy.deepcopy(FORMS)
        data["general"]["sinks"] = ["WORDPRESS_OPTIONS", "WP_NETWORK_2"]
        self.assertEqual([], form_schema.schema_errors("web-app-x", data))

    def test_sinks_that_are_no_distinct_role_variables_are_refused(self):
        for sinks in (
            [],
            "WORDPRESS_OPTIONS",
            ["wordpress_options"],
            ["WORDPRESS-OPTIONS"],
            ["{{ SINK }}"],
            ["WORDPRESS_OPTIONS", "WORDPRESS_OPTIONS"],
            [None],
        ):
            with self.subTest(sinks=sinks):
                data = copy.deepcopy(FORMS)
                data["general"]["sinks"] = sinks
                self.assertIn(
                    (
                        "web-app-x: general.sinks must list distinct UPPER_SNAKE_CASE "
                        "role variables that carry the form's values"
                    ),
                    form_schema.schema_errors("web-app-x", data),
                )

    def test_a_form_naming_its_record_passes(self):
        data = copy.deepcopy(FORMS)
        data["general"]["record"] = {"selector": "#clientId", "source": "clients.ids"}
        self.assertEqual([], form_schema.schema_errors("web-app-x", data))

    def test_a_record_without_its_input_or_ids_is_refused(self):
        for record in (
            {"selector": "#clientId"},
            {"source": "clients.ids"},
            {"selector": "#clientId", "source": "clients.ids", "match": "id"},
            {"selector": " ", "source": "clients.ids"},
            {"selector": "#clientId", "source": "{{ ids }}"},
            ["#clientId", "clients.ids"],
        ):
            with self.subTest(record=record):
                data = copy.deepcopy(FORMS)
                data["general"]["record"] = record
                self.assertIn(
                    (
                        "web-app-x: general.record must map selector to the input"
                        " that shows the edited record's id and source to the"
                        " inventory path of the ids the deployment created"
                    ),
                    form_schema.schema_errors("web-app-x", data),
                )

    def test_a_template_in_the_record_selector_is_refused(self):
        data = copy.deepcopy(FORMS)
        data["general"]["record"] = {"selector": "{{ id }}", "source": "clients.ids"}
        self.assertEqual(
            [
                (
                    "web-app-x: general.record.selector must hold no template;"
                    " meta/forms.yml is never rendered"
                )
            ],
            form_schema.schema_errors("web-app-x", data),
        )

    def test_a_field_key_may_be_the_apps_own_camel_case_setting_name(self):
        data = copy.deepcopy(FORMS)
        data["general"]["fields"] = {
            "excludedQueryParameters": _field("general", "blogname")
        }
        self.assertEqual([], form_schema.schema_errors("web-app-x", data))

    def test_a_field_key_may_be_the_apps_own_kebab_case_array_key(self):
        data = copy.deepcopy(FORMS)
        data["general"]["fields"] = {"publish-username": _field("general", "blogname")}
        self.assertEqual([], form_schema.schema_errors("web-app-x", data))

    def test_a_field_key_that_starts_with_no_lower_case_letter_is_refused(self):
        for field in ("ExcludedIps", "-api-key", "1st_site", "api key"):
            with self.subTest(field=field):
                data = copy.deepcopy(FORMS)
                data["general"]["fields"] = {field: _field("general", "blogname")}
                self.assertEqual(
                    [
                        (
                            f"web-app-x: general.fields: {field!r} is no lower"
                            " snake_case, camelCase or kebab-case key"
                        )
                    ],
                    form_schema.schema_errors("web-app-x", data),
                )

    def test_a_form_key_stays_lower_snake_case(self):
        data = {"generalSettings": copy.deepcopy(FORMS)["general"]}
        self.assertEqual(
            ["web-app-x: form 'generalSettings' is no lower snake_case key"],
            form_schema.schema_errors("web-app-x", data),
        )

    def test_a_form_the_application_locks_itself_passes(self):
        data = copy.deepcopy(FORMS)
        data["general"]["native"] = True
        self.assertEqual([], form_schema.schema_errors("web-app-x", data))

    def test_a_native_flag_other_than_true_is_refused(self):
        for native in (False, "true", 1, None):
            with self.subTest(native=native):
                data = copy.deepcopy(FORMS)
                data["general"]["native"] = native
                self.assertEqual(
                    [
                        (
                            "web-app-x: general.native must be true, or left out"
                            " where the shared renderer locks the form"
                        )
                    ],
                    form_schema.schema_errors("web-app-x", data),
                )

    def test_a_native_form_takes_no_record_and_no_sso_field(self):
        data = copy.deepcopy(FORMS)
        data["general"]["native"] = True
        data["general"]["record"] = {"selector": "#clientId", "source": "clients.ids"}
        data["general"]["fields"]["name"] = {
            "source": "sso.NAME",
            "mode": "enforced",
            "selector": "#name",
        }
        self.assertEqual(
            [
                "web-app-x: general.native takes no record; the application locks it",
                (
                    "web-app-x: general.native holds no sso.<ATTRIBUTE> field; the shared"
                    " renderer shows its warning"
                ),
            ],
            form_schema.schema_errors("web-app-x", data),
        )

    @staticmethod
    def _pending(**keys: object) -> dict:
        data = copy.deepcopy(FORMS)
        data["general"].update({"lock": "pending", "issue": ISSUE, **keys})
        return data

    def test_a_form_whose_lock_is_pending_on_an_issue_passes(self):
        self.assertEqual([], form_schema.schema_errors("web-app-x", self._pending()))

    def test_a_lock_other_than_pending_is_refused(self):
        for lock in ("locked", True, None):
            with self.subTest(lock=lock):
                self.assertEqual(
                    [
                        (
                            "web-app-x: general.lock must be pending, with the issue"
                            " that tracks the missing lock"
                        )
                    ],
                    form_schema.schema_errors("web-app-x", self._pending(lock=lock)),
                )

    def test_a_pending_lock_needs_its_issue(self):
        for issue in ("", " ", None, 7):
            with self.subTest(issue=issue):
                self.assertEqual(
                    [
                        (
                            "web-app-x: general.lock pending needs an issue: the"
                            " upstream issue URL or id that tracks the missing lock"
                        )
                    ],
                    form_schema.schema_errors("web-app-x", self._pending(issue=issue)),
                )

    def test_an_issue_without_a_pending_lock_is_refused(self):
        data = copy.deepcopy(FORMS)
        data["general"]["issue"] = ISSUE
        self.assertEqual(
            ["web-app-x: general.issue belongs to lock: pending"],
            form_schema.schema_errors("web-app-x", data),
        )

    def test_a_pending_lock_is_never_native(self):
        self.assertEqual(
            [
                (
                    "web-app-x: general.lock pending and native exclude each other;"
                    " the application locks a native form"
                )
            ],
            form_schema.schema_errors("web-app-x", self._pending(native=True)),
        )

    def test_a_pending_lock_holds_no_sso_field(self):
        data = self._pending()
        data["general"]["fields"]["name"] = {
            "source": "sso.NAME",
            "mode": "enforced",
            "selector": "#name",
        }
        self.assertEqual(
            [
                (
                    "web-app-x: general.lock pending holds no sso.<ATTRIBUTE> field; the"
                    " shared renderer shows its warning"
                )
            ],
            form_schema.schema_errors("web-app-x", data),
        )


class TestResolve(unittest.TestCase):
    def test_a_source_resolves_relative_to_the_application(self):
        self.assertEqual(
            "Infinito.Nexus", forms.resolve("design.label", APPLICATION, USERS)
        )

    def test_a_user_source_resolves_to_the_global_users(self):
        self.assertEqual(
            "admin@example.com",
            forms.resolve("users.platform_administrator.email", APPLICATION, USERS),
        )

    def test_a_user_source_never_reads_the_application(self):
        application = {"users": {"platform_administrator": {"email": "role@local"}}}
        self.assertEqual(
            "admin@example.com",
            forms.resolve("users.platform_administrator.email", application, USERS),
        )

    def test_a_missing_path_raises(self):
        with self.assertRaises(forms.SourceError):
            forms.resolve("design.title", APPLICATION, USERS)
        with self.assertRaises(forms.SourceError):
            forms.resolve("users.biber.email", APPLICATION, USERS)

    def test_a_user_password_resolves(self):
        self.assertEqual(
            "pw",
            forms.resolve("users.platform_administrator.password", APPLICATION, USERS),
        )

    def test_a_refused_user_path_raises_although_it_exists(self):
        users = {
            "platform_administrator": {
                "email": "admin@example.com",
                "password": "pw",
                "tokens": {"web-app-x": "tk"},
            }
        }
        for source in (
            "users.platform_administrator",
            "users.platform_administrator.tokens",
            "users.platform_administrator.tokens.web-app-x",
        ):
            with self.subTest(source=source), self.assertRaises(forms.SourceError):
                forms.resolve(source, {"users": users}, users)

    def test_a_source_error_never_repeats_the_source(self):
        for source in (
            "SYNTH-SECRET-JINJA-1",
            "{{ vault_x }}",
            JWT_SHAPED,
            SENDGRID_SHAPED,
            "users.platform_administrator.tokens",
        ):
            with self.subTest(source=source):
                with self.assertRaises(forms.SourceError) as caught:
                    forms.resolve(source, {}, USERS)
                self.assertNotIn(SYNTH, str(caught.exception))
                self.assertNotIn(source, repr(caught.exception))
        self.assertEqual(
            "Infinito.Nexus", forms.resolve("design.label", APPLICATION, USERS)
        )


class TestSourceErrors(unittest.TestCase):
    def test_every_declared_source_resolves(self):
        self.assertEqual(
            [],
            forms.source_errors("web-app-x", FORMS, APPLICATION, USERS, CREDENTIALS),
        )

    def test_a_credential_resolves_only_when_the_secrets_file_declares_it(self):
        self.assertEqual(
            ["web-app-x: smtp.password.source names nothing in the inventory"],
            forms.source_errors("web-app-x", FORMS, APPLICATION, USERS, {}),
        )

    def test_a_negated_when_resolves_its_path(self):
        for when, expected in (
            ("!design.label", []),
            (
                "!design.enabled",
                ["web-app-x: general.blogname.when names nothing in the inventory"],
            ),
        ):
            with self.subTest(when=when):
                spec = {**_field("general", "blogname"), "when": when}
                self.assertEqual(
                    expected,
                    forms.source_errors(
                        "web-app-x",
                        _with_field("general", "blogname", spec),
                        APPLICATION,
                        USERS,
                        CREDENTIALS,
                    ),
                )

    def test_a_dotted_secret_in_source_or_when_is_never_echoed(self):
        for value in (JWT_SHAPED, SENDGRID_SHAPED):
            with self.subTest(value=value[:12]):
                spec = {**_field("general", "blogname"), "when": value}
                errors = forms.source_errors(
                    "web-app-x",
                    _with_field("general", "blogname", spec),
                    APPLICATION,
                    USERS,
                    CREDENTIALS,
                )
                self.assertEqual(
                    ["web-app-x: general.blogname.when names nothing in the inventory"],
                    errors,
                )
                self.assertNotIn(SYNTH, errors[0])

    def test_an_unresolved_source_and_when_are_reported(self):
        spec = {
            **_field("general", "blogname"),
            "source": "design.title",
            "when": "services.design.enabled",
        }
        errors = forms.source_errors(
            "web-app-x",
            _with_field("general", "blogname", spec),
            APPLICATION,
            USERS,
            CREDENTIALS,
        )
        self.assertEqual(
            [
                "web-app-x: general.blogname.source names nothing in the inventory",
                "web-app-x: general.blogname.when names nothing in the inventory",
            ],
            errors,
        )

    def test_a_user_path_of_another_shape_or_a_refused_attribute_is_reported(self):
        application = {
            "users": {"platform_administrator": dict(USERS["platform_administrator"])}
        }
        users = {
            "platform_administrator": {**USERS["platform_administrator"], "tokens": {}}
        }
        for source in (
            "users.platform_administrator",
            "users.platform_administrator.tokens",
            "users.platform_administrator.email.local",
        ):
            with self.subTest(source=source):
                spec = {**_field("general", "admin_email"), "source": source}
                self.assertEqual(
                    [
                        (
                            "web-app-x: general.admin_email.source must be "
                            "users.<key>.<attr> with an attr other than ['tokens']"
                        )
                    ],
                    forms.source_errors(
                        "web-app-x",
                        {"general": {"path": "/a", "fields": {"admin_email": spec}}},
                        application,
                        users,
                        CREDENTIALS,
                    ),
                )

    def test_a_user_password_source_passes(self):
        spec = {
            **_field("general", "admin_email"),
            "source": "users.platform_administrator.password",
        }
        self.assertEqual(
            [],
            forms.source_errors(
                "web-app-x",
                {"general": {"path": "/a", "fields": {"admin_email": spec}}},
                APPLICATION,
                USERS,
                CREDENTIALS,
            ),
        )

    def test_a_record_source_resolves_or_is_reported(self):
        data = copy.deepcopy(FORMS)
        data["general"]["record"] = {
            "selector": "#clientId",
            "source": "services.keycloak.clients",
        }
        application = {**APPLICATION, "services": {"keycloak": {"clients": ["a"]}}}
        self.assertEqual(
            [], forms.source_errors("web-app-x", data, application, USERS, CREDENTIALS)
        )
        self.assertEqual(
            ["web-app-x: general.record.source names nothing in the inventory"],
            forms.source_errors("web-app-x", data, APPLICATION, USERS, CREDENTIALS),
        )

    def test_a_record_source_that_names_a_secret_is_refused(self):
        for source in (
            "secrets.credentials.smtp.password",
            "users.platform_administrator.email",
            "sso.EMAIL",
            "services.ldap.bind_password",
            "services.password.ids",
        ):
            with self.subTest(source=source):
                data = copy.deepcopy(FORMS)
                data["general"]["record"] = {"selector": "#clientId", "source": source}
                self.assertEqual(
                    [
                        (
                            "web-app-x: general.record.source must name no secret;"
                            " every page carries its ids"
                        )
                    ],
                    forms.source_errors(
                        "web-app-x", data, APPLICATION, USERS, CREDENTIALS
                    ),
                )


class TestSecret(unittest.TestCase):
    def test_every_user_path_and_every_credential_path_is_secret(self):
        for source in (
            "users.platform_administrator.email",
            "users.platform_administrator.password",
            "users.platform_administrator",
            "secrets.credentials.smtp.password",
            "secrets.credentials.undeclared",
        ):
            with self.subTest(source=source):
                self.assertTrue(forms.is_secret(source, CREDENTIALS))

    def test_a_secret_looking_segment_is_secret_in_any_case(self):
        for source in (
            "services.door.pin",
            "credentials.pin",
            "services.ldap.bind_password",
            "services.mail.SMTP_PASSWORD",
            "services.api.client_secret",
            "services.api.Api_Key",
            "services.bot.token",
        ):
            with self.subTest(source=source):
                self.assertTrue(forms.is_secret(source, {}))

    def test_a_segment_named_like_a_declared_credential_is_secret_in_any_case(self):
        credentials = {"mail": {"relay": {"algorithm": "alphanumeric"}}}
        self.assertTrue(forms.is_secret("services.mail.RELAY", credentials))
        self.assertFalse(forms.is_secret("services.mail.RELAY", {}))

    def test_a_service_name_is_no_value_segment(self):
        self.assertFalse(forms.is_secret("services.keycloak.client.redirect_uris", {}))

    def test_every_other_segment_is_searched(self):
        for source in (
            "services.keycloak.client.secret",
            "services.pin",
            "services.keycloak",
            "api.token.url",
        ):
            with self.subTest(source=source):
                self.assertTrue(forms.is_secret(source, {}))

    def test_a_service_named_like_a_declared_credential_stays_secret(self):
        credentials = {"keycloak": {"algorithm": "alphanumeric"}}
        self.assertTrue(
            forms.is_secret("services.keycloak.client.redirect_uris", credentials)
        )

    def test_what_is_no_dotted_path_is_secret(self):
        for source in ("SYNTH-SECRET-JINJA-1", "{{ vault_x }}", None, 7):
            with self.subTest(source=source):
                self.assertTrue(forms.is_secret(source, {}))

    def test_a_plain_setting_is_not_secret(self):
        self.assertFalse(forms.is_secret("design.label", CREDENTIALS))


class TestLocks(unittest.TestCase):
    def test_every_enforced_field_reaches_the_renderer_with_page_and_path(self):
        self.assertEqual(
            [
                {
                    "page": "/wp-admin/options-general.php",
                    "selector": "#blogname",
                    "label": "Site Title",
                    "path": "applications.web-app-x.design.label",
                    "secret": False,
                },
                {
                    "page": "/settings/admin",
                    "selector": "#mail_smtppassword",
                    "label": "password",
                    "path": "applications.web-app-x.secrets.credentials.smtp.password",
                    "secret": True,
                },
            ],
            forms.locks("web-app-x", FORMS, APPLICATION, USERS, CREDENTIALS),
        )

    def test_a_seeded_field_never_reaches_the_renderer(self):
        selectors = [
            entry["selector"]
            for entry in forms.locks("web-app-x", FORMS, APPLICATION, USERS, {})
        ]
        self.assertNotIn("#new_admin_email", selectors)

    def test_a_pending_lock_reaches_the_renderer_only_without_its_issue(self):
        for issue, selectors in (
            (ISSUE, ["#mail_smtppassword"]),
            (" ", ["#blogname", "#mail_smtppassword"]),
        ):
            with self.subTest(issue=issue):
                data = copy.deepcopy(FORMS)
                data["general"].update({"lock": "pending", "issue": issue})
                self.assertEqual(
                    selectors,
                    [
                        entry["selector"]
                        for entry in forms.locks(
                            "web-app-x", data, APPLICATION, USERS, {}
                        )
                    ],
                )

    def test_a_native_form_never_reaches_the_renderer(self):
        data = copy.deepcopy(FORMS)
        data["general"]["native"] = True
        self.assertEqual(
            ["#mail_smtppassword"],
            [
                entry["selector"]
                for entry in forms.locks("web-app-x", data, APPLICATION, USERS, {})
            ],
        )

    def test_a_user_source_keeps_its_users_path(self):
        spec = {**_field("general", "admin_email"), "mode": "enforced"}
        managed = _with_field("general", "admin_email", spec)
        entry = next(
            entry
            for entry in forms.locks("web-app-x", managed, APPLICATION, USERS, {})
            if entry["selector"] == "#new_admin_email"
        )
        self.assertEqual("users.platform_administrator.email", entry["path"])
        self.assertTrue(entry["secret"])

    def test_a_field_whose_when_does_not_hold_is_not_locked(self):
        for value, locked in (
            (True, True),
            ("True", True),
            (False, False),
            ("", False),
        ):
            with self.subTest(value=value):
                application = {**APPLICATION, "services": {"design": {"on": value}}}
                managed = _with_field(
                    "general",
                    "blogname",
                    {**_field("general", "blogname"), "when": "services.design.on"},
                )
                selectors = [
                    entry["selector"]
                    for entry in forms.locks("web-app-x", managed, application, {}, {})
                ]
                self.assertEqual(locked, "#blogname" in selectors)

    def test_an_optional_field_whose_source_is_false_is_not_locked(self):
        for title, locked in (("Fixture", True), (False, False)):
            with self.subTest(title=title):
                managed = _with_field(
                    "general",
                    "blogname",
                    {**_field("general", "blogname"), "optional": True},
                )
                application = {**APPLICATION, "design": {"label": title}}
                selectors = [
                    entry["selector"]
                    for entry in forms.locks("web-app-x", managed, application, {}, {})
                ]
                self.assertEqual(locked, "#blogname" in selectors)

    def test_a_false_source_keeps_its_lock_unless_the_field_is_optional(self):
        application = {**APPLICATION, "design": {"label": False}}
        selectors = [
            entry["selector"]
            for entry in forms.locks("web-app-x", FORMS, application, {}, {})
        ]
        self.assertIn("#blogname", selectors)

    def test_a_when_that_names_nothing_raises_without_repeating_it(self):
        managed = _with_field(
            "general",
            "blogname",
            {**_field("general", "blogname"), "when": "services.SYNTH-SECRET-1"},
        )
        with self.assertRaises(forms.SourceError) as caught:
            forms.locks("web-app-x", managed, APPLICATION, USERS, {})
        self.assertNotIn(SYNTH, str(caught.exception))

    def test_the_page_hides_every_value_the_fail_closed_rule_does_not_clear(self):
        relay = {"relay": {"algorithm": "alphanumeric", "length": 32}}
        cases = {
            "an untyped field": ({}, True),
            "a password field": ({"type": "password"}, True),
            "a secret-looking segment": (
                {"type": "text", "source": "services.ldap.bind_dn"},
                True,
            ),
            "a declared credential's name": (
                {"type": "text", "source": "services.relay.host"},
                True,
            ),
            "a plain text field": ({"type": "text"}, False),
        }
        for case, (override, secret) in cases.items():
            with self.subTest(case=case):
                spec = {
                    "source": "design.label",
                    "mode": "enforced",
                    "selector": "#blogname",
                    **override,
                }
                managed = {"general": {"path": "/", "fields": {"blogname": spec}}}
                entry = forms.locks("web-app-x", managed, {}, {}, relay)[0]
                self.assertEqual(secret, entry["secret"])

    @staticmethod
    def _record_locks(ids: object) -> list[dict]:
        data = copy.deepcopy(FORMS)
        data["general"]["record"] = {
            "selector": "#clientId",
            "source": "services.keycloak.clients",
        }
        application = {**APPLICATION, "services": {"keycloak": {"clients": ids}}}
        return forms.locks("web-app-x", data, application, USERS, CREDENTIALS)

    def test_only_the_fields_of_a_record_form_carry_the_ids_it_created(self):
        pages = {lock["page"]: lock for lock in self._record_locks(["a", "b"])}
        self.assertEqual(
            {"selector": "#clientId", "values": ["a", "b"]},
            pages[FORMS["general"]["path"]]["record"],
        )
        self.assertNotIn("record", pages[FORMS["smtp"]["path"]])

    def test_record_ids_that_are_no_list_of_strings_raise(self):
        for ids in ("a", ["a", 1], {"a": 1}, None):
            with self.subTest(ids=ids), self.assertRaises(forms.SourceError):
                self._record_locks(ids)


class TestDrift(unittest.TestCase):
    def test_an_enforced_field_that_differs_names_old_and_new(self):
        lines = drift.drift(
            "web-app-x",
            FORMS,
            {"general.blogname": "Infinito.Nexus"},
            {"general.blogname": "My blog"},
            CREDENTIALS,
            raw_application=APPLICATION,
            secrets=frozenset(),
        )
        self.assertEqual(
            [
                "web-app-x: general.blogname (design.label): 'My blog' -> 'Infinito.Nexus'"
            ],
            lines,
        )

    def test_a_form_whose_lock_is_pending_still_reports_its_drift(self):
        data = copy.deepcopy(FORMS)
        data["general"].update({"lock": "pending", "issue": ISSUE})
        self.assertEqual(
            ["web-app-x: general.blogname: changed"],
            drift.drift(
                "web-app-x",
                data,
                {"general.blogname": "Infinito.Nexus"},
                {"general.blogname": "My blog"},
                CREDENTIALS,
            ),
        )

    def test_without_the_raw_application_or_the_secrets_nothing_is_shown(self):
        for raw, secrets in ((None, frozenset()), (APPLICATION, None), (None, None)):
            with self.subTest(raw=raw is not None, secrets=secrets is not None):
                label = "general.blogname (design.label)" if raw else "general.blogname"
                self.assertEqual(
                    [f"web-app-x: {label}: changed"],
                    drift.drift(
                        "web-app-x",
                        FORMS,
                        {"general.blogname": "Infinito.Nexus"},
                        {"general.blogname": "My blog"},
                        CREDENTIALS,
                        raw_application=raw,
                        secrets=secrets,
                    ),
                )

    def test_a_seeded_or_unchanged_or_unread_field_is_not_reported(self):
        lines = drift.drift(
            "web-app-x",
            FORMS,
            {"general.admin_email": "admin@example.com", "general.blogname": "A"},
            {"general.admin_email": "edited@example.com", "general.blogname": "A"},
            CREDENTIALS,
        )
        self.assertEqual([], lines)
        self.assertEqual(
            [],
            drift.drift("web-app-x", FORMS, {"general.blogname": "A"}, {}, CREDENTIALS),
        )

    def test_no_drift_line_carries_a_secret_value(self):
        pairs = [
            ("Zq7xP2vR9mK4wL8n", "Hb3tY6cJ1sF5dG0a"),
            ("", "Kd8eR2pQ"),
            ("Wm4vT9xL", ""),
            ("same-prefix-Aa1", "same-prefix-Bb2"),
        ]
        for old, new in pairs:
            with self.subTest(old=old, new=new):
                lines = drift.drift(
                    "web-app-x",
                    FORMS,
                    {"smtp.password": new},
                    {"smtp.password": old},
                    CREDENTIALS,
                )
                self.assertEqual(["web-app-x: smtp.password: changed"], lines)
                for value in (old, new):
                    if value:
                        self.assertNotIn(value, lines[0])


class _TaggedStr(str):
    __slots__ = ()


def _nested(path: object, value: object) -> dict:
    if not (isinstance(path, str) and "." in path and "{" not in path):
        return {}
    node: dict = {}
    root = node
    *parents, leaf = path.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value
    return root


def _drift_raw(
    spec: dict,
    old: object,
    new: object,
    credentials: dict,
    raw_value: object,
    secrets: frozenset[str],
) -> list[str]:
    field = {"mode": "enforced", "selector": "#f", **spec}
    return drift.drift(
        "web-app-x",
        {"page": {"path": "/a", "fields": {"f": field}}},
        {"page.f": new},
        {"page.f": old},
        credentials,
        raw_application=_nested(spec.get("source"), raw_value),
        secrets=secrets,
    )


def _drift_one(spec: dict, old: object, new: object, credentials: dict) -> list[str]:
    return _drift_raw(spec, old, new, credentials, "raw-literal", frozenset())


class TestDriftShowsOnlyPlainValues(unittest.TestCase):
    def assert_hidden(self, lines: list[str], *values: str) -> None:
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].endswith(": changed"), lines[0])
        for value in values:
            self.assertNotIn(value, lines[0])

    def test_a_plain_setting_shows_both_values(self):
        self.assertEqual(
            ["web-app-x: page.f (services.email.relay): 'OLD-RELAY' -> 'NEW-RELAY'"],
            _drift_one(
                {"source": "services.email.relay", "type": "text"},
                "OLD-RELAY",
                "NEW-RELAY",
                {},
            ),
        )

    def test_a_password_type_hides_values_of_any_source(self):
        self.assert_hidden(
            _drift_one(
                {"source": "services.email.relay", "type": "password"},
                "OLD-TYPED-SECRET",
                "NEW-TYPED-SECRET",
                {},
            ),
            "OLD-TYPED-SECRET",
            "NEW-TYPED-SECRET",
        )

    def test_a_file_type_hides_its_values(self):
        self.assert_hidden(
            _drift_one(
                {"source": "services.design.logo", "type": "file"},
                "OLD-LOGO",
                "NEW-LOGO",
                {},
            ),
            "OLD-LOGO",
            "NEW-LOGO",
        )

    def test_a_user_source_hides_its_values(self):
        for source, old, new in (
            ("users.administrator.tokens", {"x": "OLD-TOKEN"}, {"x": "NEW-TOKEN"}),
            (
                "users.administrator",
                {"email": "a@x", "password": "OLD-PW"},
                {"email": "a@x", "password": "NEW-PW"},
            ),
            ("users.administrator.email", "old@example.com", "new@example.com"),
        ):
            with self.subTest(source=source):
                self.assert_hidden(
                    _drift_one({"source": source, "type": "text"}, old, new, {}),
                    "OLD-TOKEN",
                    "NEW-TOKEN",
                    "OLD-PW",
                    "NEW-PW",
                    "old@example.com",
                    "new@example.com",
                )

    def test_a_user_password_source_is_always_masked(self):
        for field_type in ("text", "password"):
            with self.subTest(type=field_type):
                self.assert_hidden(
                    _drift_one(
                        {"source": "users.administrator.password", "type": field_type},
                        "SYNTH-USER-PW-OLD",
                        "SYNTH-USER-PW-NEW",
                        {},
                    ),
                    "SYNTH-USER-PW-OLD",
                    "SYNTH-USER-PW-NEW",
                )

    def test_a_field_without_a_type_hides_its_values(self):
        self.assert_hidden(
            _drift_one(
                {"source": "services.email.relay"}, "OLD-RELAY", "NEW-RELAY", {}
            ),
            "OLD-RELAY",
            "NEW-RELAY",
        )

    def test_a_plain_str_built_from_a_secret_hides_without_a_type(self):
        for new in (
            "pfx-SYNTH-SECRET-NEW-1",
            "synth-secret-new-1",
            "SYNTH-SECRET-NEW-1",
        ):
            with self.subTest(new=new):
                self.assert_hidden(
                    _drift_one({"source": "services.x.y"}, "plain-old", new, {}),
                    "SYNTH-SECRET-NEW-1",
                    "synth-secret-new-1",
                )

    def test_an_undeclared_credential_path_hides_its_values(self):
        self.assert_hidden(
            _drift_one(
                {"source": "secrets.credentials.relay", "type": "text"},
                "OLD-CRED",
                "NEW-CRED",
                {},
            ),
            "OLD-CRED",
            "NEW-CRED",
        )

    def test_a_segment_named_like_a_declared_credential_hides_its_values(self):
        spec = {"source": "services.mail.RELAY", "type": "text"}
        credentials = {"mail": {"relay": {"algorithm": "alphanumeric"}}}
        self.assert_hidden(
            _drift_one(spec, "OLD-RELAY", "NEW-RELAY", credentials),
            "OLD-RELAY",
            "NEW-RELAY",
        )
        self.assertEqual(
            ["web-app-x: page.f (services.mail.RELAY): 'OLD-RELAY' -> 'NEW-RELAY'"],
            _drift_one(spec, "OLD-RELAY", "NEW-RELAY", {}),
        )

    def test_the_skeptic_probe_cases_hide_their_values(self):
        flat = {"smtp_password": {"algorithm": "alphanumeric", "length": 32}}
        cases = (
            ({"source": "services.door.pin", "type": "number"}, 1111, 987654, {}),
            (
                {"source": "credentials.pin", "type": "text"},
                "SYNTH-PIN-OLD",
                "SYNTH-PIN-NEW",
                {"pin": {"algorithm": "numeric"}},
            ),
            (
                {"source": "credentials.pin", "type": "text"},
                "SYNTH-PIN-OLD",
                "SYNTH-PIN-NEW",
                {},
            ),
            (
                {"source": "services.ldap.bind_password", "type": "text"},
                "SYNTH-SECRET-OLD-1",
                "SYNTH-SECRET-NEW-1",
                flat,
            ),
            (
                {"source": "services.mail.SMTP_PASSWORD", "type": "text"},
                "SYNTH-SECRET-OLD-1",
                "SYNTH-SECRET-NEW-1",
                flat,
            ),
            (
                {"source": "services.api.client_secret"},
                None,
                "SYNTH-SECRET-NEW-1",
                {},
            ),
            (
                {"source": "services.x.map", "type": "text"},
                {"SYNTH-SECRET-OLD-1": 1},
                {"SYNTH-SECRET-NEW-1": 1},
                {},
            ),
            (
                {"source": "services.smtp_password", "type": "checkbox"},
                False,
                True,
                flat,
            ),
        )
        for spec, old, new, credentials in cases:
            with self.subTest(source=spec["source"]):
                self.assert_hidden(
                    _drift_one(spec, old, new, credentials),
                    *(repr(value) for value in (old, new)),
                    "SYNTH-SECRET-OLD-1",
                    "SYNTH-SECRET-NEW-1",
                    "SYNTH-PIN-OLD",
                    "SYNTH-PIN-NEW",
                )

    def test_a_source_that_did_not_resolve_is_never_echoed(self):
        for source in ("SYNTH-SECRET-JINJA-1", JWT_SHAPED, SENDGRID_SHAPED):
            with self.subTest(source=source[:12]):
                lines = drift.drift(
                    "web-app-x",
                    {
                        "page": {
                            "path": "/a",
                            "fields": {
                                "f": {
                                    "source": source,
                                    "type": "text",
                                    "mode": "enforced",
                                    "selector": "#f",
                                }
                            },
                        }
                    },
                    {"page.f": "b"},
                    {"page.f": "a"},
                    {},
                    raw_application={"design": {"label": "x"}},
                    secrets=frozenset(),
                )
                self.assertEqual(["web-app-x: page.f: changed"], lines)

    def test_the_third_skeptic_probe_cases_hide_their_values(self):
        for spec, old, new in (
            ({"source": "services.kix.admin_pw", "type": "text"}, "old", SYNTH),
            ({"source": "services.app.auth_salt", "type": "text"}, "old", SYNTH),
            ({"source": "services.mcp.bearer", "type": "text"}, "old", SYNTH),
            (
                {"source": "server.config.webhook_url", "type": "url"},
                "https://hooks/old",
                f"https://hooks/{SYNTH}",
            ),
            (
                {"source": "database.url", "type": "url"},
                "postgres://u:old@db/app",
                f"postgres://u:{SYNTH}@db/app",
            ),
        ):
            with self.subTest(source=spec["source"]):
                self.assert_hidden(_drift_one(spec, old, new, {}), SYNTH, "old")

    def test_a_raw_template_at_the_source_hides_its_values(self):
        spec = {"source": "design.label", "type": "text"}
        self.assert_hidden(
            _drift_raw(spec, "old", SYNTH, {}, "{{ vault_label }}", frozenset()),
            SYNTH,
        )
        self.assertEqual(
            [f"web-app-x: page.f (design.label): 'old' -> {SYNTH!r}"],
            _drift_raw(spec, "old", SYNTH, {}, "My blog", frozenset()),
        )

    def test_a_raw_value_that_is_no_plain_scalar_hides_its_values(self):
        class VaultLike(str):
            __slots__ = ()

        spec = {"source": "design.label", "type": "text"}
        for raw_value in (VaultLike("$ANSIBLE_VAULT;1.1;AES256"), ["x"], {"a": "b"}):
            with self.subTest(raw_value=type(raw_value).__name__):
                self.assert_hidden(
                    _drift_raw(spec, "old", SYNTH, {}, raw_value, frozenset()), SYNTH
                )

    def test_a_url_with_userinfo_hides_its_values(self):
        spec = {"source": "services.app.endpoint", "type": "url"}
        self.assert_hidden(
            _drift_one(
                spec, "https://db.example/app", f"https://u:{SYNTH}@db.example/app", {}
            ),
            SYNTH,
        )
        self.assertEqual(
            [
                (
                    "web-app-x: page.f (services.app.endpoint): "
                    "'https://db.example/app' -> 'https://db2.example/app'"
                )
            ],
            _drift_one(spec, "https://db.example/app", "https://db2.example/app", {}),
        )

    def test_a_value_holding_a_known_secret_hides_its_values(self):
        spec = {"source": "design.label", "type": "text"}
        for new in (SYNTH, f"pfx-{SYNTH}-sfx"):
            with self.subTest(new=new):
                self.assert_hidden(
                    _drift_raw(spec, "old", new, {}, "My blog", frozenset({SYNTH})),
                    SYNTH,
                )
        self.assertEqual(
            [f"web-app-x: page.f (design.label): 'old' -> 'pfx-{SYNTH}-sfx'"],
            _drift_raw(spec, "old", f"pfx-{SYNTH}-sfx", {}, "My blog", frozenset()),
        )

    def test_secret_values_collects_credentials_and_user_passwords(self):
        application = {
            "credentials": {
                "smtp_password": "SYNTH-CRED-1",
                "nested": {"api": "SYNTH-CRED-2"},
            },
            "secrets": {"credentials": {"relay": "SYNTH-CRED-3", "empty": ""}},
            "design": {"label": "Plain"},
        }
        users = {"a": {"password": "SYNTH-USER-PW", "email": "a@x"}, "b": {}}
        self.assertEqual(
            frozenset(
                {"SYNTH-CRED-1", "SYNTH-CRED-2", "SYNTH-CRED-3", "SYNTH-USER-PW"}
            ),
            drift.secret_values({"web-app-x": application}, users),
        )

    def test_secret_values_collects_the_credentials_of_every_application(self):
        applications = {
            "web-app-x": {"credentials": {"own": "SYNTH-OWN-CRED"}},
            "web-app-other": {
                "credentials": {"api": "SYNTH-FOREIGN-CRED"},
                "secrets": {"credentials": {"bind": "SYNTH-FOREIGN-BIND"}},
            },
            "web-app-plain": {"design": {"label": "Plain"}},
        }
        self.assertEqual(
            frozenset({"SYNTH-OWN-CRED", "SYNTH-FOREIGN-CRED", "SYNTH-FOREIGN-BIND"}),
            drift.secret_values(applications, {}),
        )

    def test_another_roles_credential_in_a_harmless_field_hides_its_values(self):
        spec = {"source": "design.label", "type": "text"}
        foreign = "SYNTH-FOREIGN-CRED"
        applications = {
            "web-app-x": {"design": {"label": foreign}},
            "web-app-other": {"credentials": {"api": foreign}},
        }
        secrets = drift.secret_values(applications, {})
        self.assert_hidden(
            _drift_raw(spec, "old", foreign, {}, foreign, secrets), foreign
        )
        own_only = drift.secret_values({"web-app-x": applications["web-app-x"]}, {})
        self.assertEqual(
            [f"web-app-x: page.f (design.label): 'old' -> {foreign!r}"],
            _drift_raw(spec, "old", foreign, {}, foreign, own_only),
        )

    def test_a_mapping_a_list_or_a_str_subclass_hides_its_values(self):
        for old, new in (
            ({"k": "OLD-NESTED"}, {"k": "NEW-NESTED"}),
            (["OLD-NESTED"], ["NEW-NESTED"]),
            (_TaggedStr("OLD-NESTED"), _TaggedStr("NEW-NESTED")),
        ):
            with self.subTest(old=type(old).__name__):
                self.assert_hidden(
                    _drift_one(
                        {"source": "services.email.relay", "type": "text"}, old, new, {}
                    ),
                    "OLD-NESTED",
                    "NEW-NESTED",
                )

    def test_a_malformed_type_hides_its_values(self):
        self.assert_hidden(
            _drift_one(
                {"source": "services.email.relay", "type": ["password"]},
                "OLD-RELAY",
                "NEW-RELAY",
                {},
            ),
            "OLD-RELAY",
            "NEW-RELAY",
        )


class TestFormsReachTheApplications(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self.addCleanup(_reset_cache_for_tests)

    @staticmethod
    def _roles(tmp: Path) -> Path:
        role = tmp / "roles" / "web-app-foo"
        for name, content in (
            (ROLE_FILE_META_SERVICES, "foo:\n  image: foo\n  version: latest\n"),
            (
                ROLE_FILE_META_FORMS,
                """
                general:
                  path: /admin/settings
                  fields:
                    title:
                      source: services.foo.image
                      mode: enforced
                      selector: "#title"
                    email:
                      source: users.administrator.email
                      mode: seeded
                      selector: "#email"
                """,
            ),
        ):
            path = role / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(content), encoding="utf-8")
        return tmp / "roles"

    def test_the_forms_file_lands_at_applications_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            defaults = cache_apps.get_application_defaults(
                roles_dir=self._roles(Path(tmp))
            )
            fields = defaults["web-app-foo"]["forms"]["general"]["fields"]
            self.assertEqual(["title", "email"], list(fields))
            self.assertEqual("enforced", fields["title"]["mode"])

    def test_an_inventory_overrides_a_single_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged = cache_apps.get_merged_applications(
                variables={
                    "applications": {
                        "web-app-foo": {
                            "forms": {
                                "general": {"fields": {"title": {"mode": "seeded"}}}
                            }
                        }
                    }
                },
                roles_dir=self._roles(Path(tmp)),
                templar=None,
            )
            general = merged["web-app-foo"]["forms"]["general"]
            self.assertEqual("seeded", general["fields"]["title"]["mode"])
            self.assertEqual("services.foo.image", general["fields"]["title"]["source"])
            self.assertEqual("#title", general["fields"]["title"]["selector"])
            self.assertEqual("seeded", general["fields"]["email"]["mode"])
            self.assertEqual("/admin/settings", general["path"])

    def test_the_templar_never_renders_the_forms(self):
        template = "{{ vault_x }}"

        def fake_render(value, **_kwargs):
            if isinstance(value, dict):
                return {key: fake_render(child) for key, child in value.items()}
            return "SYNTH-RENDERED" if value == template else value

        overrides = {
            "web-app-foo": {
                "services": {"foo": {"image": template}},
                "forms": {"general": {"fields": {"title": {"source": template}}}},
            }
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(cache_apps, "_render_with_templar", fake_render),
        ):
            merged = cache_apps.get_merged_applications(
                variables={"applications": overrides},
                roles_dir=self._roles(Path(tmp)),
                templar=object(),
            )
        self.assertEqual(
            "SYNTH-RENDERED", merged["web-app-foo"]["services"]["foo"]["image"]
        )
        title = merged["web-app-foo"]["forms"]["general"]["fields"]["title"]
        self.assertEqual(template, title["source"])
        self.assertEqual("#title", title["selector"])

    def test_the_returned_forms_share_no_object_with_the_inventory(self):
        added = {"source": "design.label", "mode": "seeded", "selector": "#extra"}
        overrides = {
            "web-app-foo": {
                "forms": {
                    "general": {
                        "fields": {"title": {"mode": "seeded"}, "extra": added}
                    },
                    "added": {"path": "/added", "fields": {"extra": dict(added)}},
                }
            }
        }
        pristine = copy.deepcopy(overrides)
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                cache_apps, "_render_with_templar", lambda value, **_: value
            ),
        ):
            merged = cache_apps.get_merged_applications(
                variables={"applications": overrides},
                roles_dir=self._roles(Path(tmp)),
                templar=object(),
            )
        forms = merged["web-app-foo"]["forms"]
        forms["general"]["fields"]["extra"]["mode"] = "enforced"
        forms["added"]["fields"]["extra"]["injected"] = "x"
        forms["added"]["fields"].pop("extra")
        forms["general"]["fields"]["title"]["mode"] = "enforced"
        self.assertEqual(pristine, overrides)


if __name__ == "__main__":
    unittest.main()
