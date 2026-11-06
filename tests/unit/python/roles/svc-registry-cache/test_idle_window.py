from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-registry-cache"
SIZE_KEYS = {"max_size", "blobstore_max", "max_size_gb"}


class TestRegistryCacheIdleWindow(unittest.TestCase):
    def test_the_role_defaults_to_the_30_day_window(self) -> None:
        cache = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))["cache"]
        self.assertEqual(cache["max_idle_days"], 30)

    def test_the_registry_flavor_keeps_no_size_cap(self) -> None:
        cache = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))["cache"]
        self.assertEqual(SIZE_KEYS & set(cache), set())
        self.assertNotIn(
            "REGISTRY_STORAGE_MAXSIZE", read_text(str(ROLE / "templates" / "env.j2"))
        )

    def test_the_window_reaches_the_registry_as_its_proxy_ttl_in_hours(self) -> None:
        self.assertIn(
            "REGISTRY_CACHE_PROXY_TTL: \"{{ (lookup('config', application_id, 'services.cache.max_idle_days') | int) * 24 }}h\"",
            read_text(str(ROLE / ROLE_FILE_VARS_MAIN)),
        )
        self.assertIn(
            "REGISTRY_PROXY_TTL={{ REGISTRY_CACHE_PROXY_TTL }}",
            read_text(str(ROLE / "templates" / "env.j2")),
        )


if __name__ == "__main__":
    unittest.main()
