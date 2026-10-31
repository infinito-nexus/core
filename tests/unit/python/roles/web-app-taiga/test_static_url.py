from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATE = (
    PROJECT_ROOT
    / "roles"
    / "web-app-taiga"
    / "templates"
    / "settings"
    / "config.append.py.j2"
)
CLEAR = "taiga.kanban.example.test"
JINJA = "django_jinja.backend.Jinja2"
DJANGO = "django.template.backends.django.DjangoTemplates"


def settle(subpath: str = "", jinja_backend: str = JINJA) -> dict:
    """Run the rendered append on top of taiga-back's image settings.

    Args:
        subpath: ``FORCE_SCRIPT_NAME`` as the image derives it from ``TAIGA_SUBPATH``.
        jinja_backend: ``BACKEND`` of the first engine in ``TEMPLATES``.

    Returns:
        The settings namespace after the append ran.
    """
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = bool
    rendered = environment.from_string(read_text(str(TEMPLATE))).render(
        TAIGA_CONFIG_APPEND_MARKER="INFINITO_TAIGA_AUTH_CONFIG",
        TAIGA_OIDC_ENABLED=False,
        TAIGA_LDAP_ENABLED=False,
        application_id="web-app-taiga",
        lookup=lambda *_terms: False,
    )
    namespace = {
        "TAIGA_SITES_SCHEME": "https",
        "TAIGA_SITES_DOMAIN": CLEAR,
        "FORCE_SCRIPT_NAME": subpath,
        "STATIC_URL": f"https://{CLEAR}{subpath}/static/",
        "TEMPLATES": [
            {"BACKEND": jinja_backend, "OPTIONS": {"match_extension": ".jinja"}},
            {"BACKEND": DJANGO, "OPTIONS": {}},
        ],
    }
    exec(compile(rendered, str(TEMPLATE), "exec"), namespace)
    return namespace


def mail_static(namespace: dict, path: str) -> str:
    static = types.ModuleType("django.templatetags.static")
    static.static = lambda name: namespace["STATIC_URL"] + name
    modules = {
        "django": types.ModuleType("django"),
        "django.templatetags": types.ModuleType("django.templatetags"),
        "django.templatetags.static": static,
    }
    with mock.patch.dict(sys.modules, modules):
        return namespace["TEMPLATES"][0]["OPTIONS"]["globals"]["static"](path)


class TestBrowserAssets(unittest.TestCase):
    def test_the_admin_loads_static_files_from_the_page_host(self) -> None:
        self.assertEqual(settle()["STATIC_URL"], "/static/")

    def test_a_subpath_keeps_its_prefix(self) -> None:
        self.assertEqual(settle(subpath="/taiga")["STATIC_URL"], "/taiga/static/")

    def test_the_django_engine_keeps_its_static_tag(self) -> None:
        self.assertNotIn("globals", settle()["TEMPLATES"][1]["OPTIONS"])


class TestMailAssets(unittest.TestCase):
    def test_mail_templates_keep_the_canonical_absolute_url(self) -> None:
        self.assertEqual(
            mail_static(settle(), "emails/logo-web.png"),
            f"https://{CLEAR}/static/emails/logo-web.png",
        )

    def test_mail_templates_keep_the_subpath_once(self) -> None:
        self.assertEqual(
            mail_static(settle(subpath="/taiga"), "emails/logo-web.png"),
            f"https://{CLEAR}/taiga/static/emails/logo-web.png",
        )

    def test_a_renamed_jinja_backend_fails_loudly(self) -> None:
        with self.assertRaises(StopIteration):
            settle(jinja_backend="django_jinja.Jinja2")


if __name__ == "__main__":
    unittest.main()
