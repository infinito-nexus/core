from __future__ import annotations

import unittest

from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-openproject"
VARIABLES = load_yaml_any(ROLE / ROLE_FILE_VARS_MAIN)
KEEPALIVE = (
    "OPENPROJECT_DB_KEEPALIVE_IDLE_SECONDS",
    "OPENPROJECT_DB_KEEPALIVE_INTERVAL_SECONDS",
    "OPENPROJECT_DB_KEEPALIVE_COUNT",
)
ENV = ROLE / "templates" / "env.j2"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
BASE_ENV = "roles/sys-svc-container/templates/env.j2"
LABEL = "Corporate OpenProject"
DOMAIN = "projects.example.org"


def _lookup(name: str, *terms, **kwargs):
    return {
        "config": "secret",
        "database": "db",
        "design": {"label": LABEL, "title": False},
        "domain": DOMAIN,
        "objstore": False,
        "tls": True,
    }[name]


def _env(general: dict, users: dict) -> list[str]:
    env = Environment(
        loader=DictLoader({ENV.name: read_text(str(ENV)), BASE_ENV: ""}),
        autoescape=select_autoescape(),
        undefined=StrictUndefined,
        trim_blocks=True,
    )
    env.filters["bool"] = bool
    env.filters["dotenv_quote"] = lambda value: f'"{value}"'
    return (
        env.get_template(ENV.name)
        .render(
            lookup=_lookup,
            application_id="web-app-openproject",
            OPENPROJECT_GENERAL=general,
            OPENPROJECT_USERS=users,
            OPENPROJECT_HEADER_SSO_ENABLED=False,
            OPENPROJECT_DB_POOL=20,
            OPENPROJECT_RAILS_MAX_THREADS=20,
            **{key: VARIABLES[key] for key in KEEPALIVE},
        )
        .splitlines()
    )


def _application(design: bool, https: bool) -> dict:
    return {
        "services": {
            "design": {"enabled": design},
            "openproject": {
                "app_title": LABEL,
                "host_name": DOMAIN,
                "https": https,
                "user_default_theme": "sync_with_os",
            },
        }
    }


class TestTheEnvTakesTheSettingsFromTheSinks(unittest.TestCase):
    def test_host_and_https_come_from_the_general_sink(self) -> None:
        lines = _env({"host_name": "other.example.org", "https": False}, {})
        self.assertIn("OPENPROJECT_HOST__NAME=other.example.org", lines)
        self.assertIn("OPENPROJECT_HTTPS=false", lines)

    def test_title_and_theme_follow_their_fields(self) -> None:
        general = {"host_name": DOMAIN, "https": True}
        for title, theme in ((True, True), (False, False)):
            with self.subTest(title=title, theme=theme):
                lines = _env(
                    {**general, **({"app_title": "Sink title"} if title else {})},
                    {"user_default_theme": "dark"} if theme else {},
                )
                self.assertEqual(title, 'OPENPROJECT_APP__TITLE="Sink title"' in lines)
                self.assertEqual(
                    theme, "OPENPROJECT_USER__DEFAULT__THEME=dark" in lines
                )


class TestTheFormsFollowTheDeployment(unittest.TestCase):
    def test_the_general_form_maps_the_deployment(self) -> None:
        forms = load_yaml_any(str(FORMS))
        for design, https, wanted in (
            (True, True, {"app_title": LABEL, "host_name": DOMAIN, "https": True}),
            (False, False, {"host_name": DOMAIN, "https": False}),
        ):
            with self.subTest(design=design, https=https):
                self.assertEqual(
                    wanted, values("general", forms, _application(design, https), {})
                )

    def test_the_theme_follows_the_design_service(self) -> None:
        forms = load_yaml_any(str(FORMS))
        for design, wanted in (
            (True, {"user_default_theme": "sync_with_os"}),
            (False, {}),
        ):
            with self.subTest(design=design):
                self.assertEqual(
                    wanted, values("users", forms, _application(design, True), {})
                )

    def test_the_forms_are_locked_by_openproject_itself(self) -> None:
        forms = load_yaml_any(str(FORMS))
        self.assertEqual({True}, {block.get("native") for block in forms.values()})

    def test_the_sources_compute_title_host_and_https(self) -> None:
        openproject = load_yaml_any(str(SERVICES))["openproject"]
        env = Environment(autoescape=True)
        self.assertEqual(
            [LABEL, DOMAIN, "True"],
            [
                env.from_string(str(openproject[key])).render(lookup=_lookup)
                for key in ("app_title", "host_name", "https")
            ],
        )


if __name__ == "__main__":
    unittest.main()
