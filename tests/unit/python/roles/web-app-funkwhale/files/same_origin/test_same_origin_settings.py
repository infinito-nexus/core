from __future__ import annotations

import runpy
import sys
import unittest
from types import ModuleType
from unittest import mock

from . import PROJECT_ROOT

MODULE_PATH = (
    PROJECT_ROOT
    / "roles/web-app-funkwhale/files/python/same_origin/same_origin_settings.py"
)
STOCK_BACKEND = "funkwhale_api.common.storage.ASCIIS3Boto3Storage"


def _run() -> tuple[dict, dict]:
    """
    Returns:
        The globals of the settings module run over a stand-in for config.settings.production, and that stand-in's STORAGES before the run.
    """
    production = ModuleType("config.settings.production")
    production.STORAGES = {
        "default": {"BACKEND": STOCK_BACKEND, "OPTIONS": {"object_parameters": {}}},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    production.ROOT_URLCONF = "config.urls"
    production.MEDIA_URL = "https://funkwhale.example.com/media/"
    original = {key: dict(value) for key, value in production.STORAGES.items()}
    modules = {
        "config": ModuleType("config"),
        "config.settings": ModuleType("config.settings"),
        "config.settings.production": production,
    }
    with mock.patch.dict(sys.modules, modules):
        return runpy.run_path(str(MODULE_PATH)), original


class TestSameOriginSettings(unittest.TestCase):
    def test_default_storage_is_the_same_origin_backend(self):
        settings, _ = _run()

        self.assertEqual(
            settings["STORAGES"]["default"]["BACKEND"],
            "same_origin_storage.SameOriginS3Storage",
        )

    def test_default_storage_keeps_the_stock_options(self):
        settings, original = _run()

        self.assertEqual(
            settings["STORAGES"]["default"]["OPTIONS"], original["default"]["OPTIONS"]
        )

    def test_static_files_are_untouched(self):
        settings, original = _run()

        self.assertEqual(settings["STORAGES"]["staticfiles"], original["staticfiles"])

    def test_root_urlconf_serves_the_media_route(self):
        settings, _ = _run()

        self.assertEqual(settings["ROOT_URLCONF"], "same_origin_urls")

    def test_production_settings_are_carried_over(self):
        settings, _ = _run()

        self.assertEqual(settings["MEDIA_URL"], "https://funkwhale.example.com/media/")


if __name__ == "__main__":
    unittest.main()
